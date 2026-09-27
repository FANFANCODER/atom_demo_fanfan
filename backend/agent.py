"""AI Agent: turns a user prompt into a static website.

Uses an LLM (OpenAI-compatible) if OPENAI_API_KEY is set; otherwise falls back
to a smart template generator that produces polished single-page sites.

The streaming entry point (``generate_site_stream``) yields SSE-friendly events
so the caller can surface the model's thinking/reasoning process in real time.
"""
import os
import re
import json
import random
import asyncio
import httpx

LLM_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
LLM_API_KEY = os.environ.get("OPENAI_API_KEY", "")
LLM_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

SYSTEM_PROMPT = """You are an expert frontend engineer. The user describes a website they want.
Return ONLY a JSON object with this exact shape:
{
  "title": "Site title",
  "files": {
    "index.html": "<!DOCTYPE html>...full HTML...",
    "styles.css": "...optional CSS...",
    "script.js": "...optional JS..."
  }
}
Rules:
- Produce a complete, beautiful, responsive single-page website.
- index.html must be self-contained but may reference styles.css and script.js.
- Use modern CSS (flex/grid, gradients, animations). Mobile-first.
- No placeholders like lorem ipsum — write real copy fitting the request.
- No external CDN dependencies; inline SVGs/icons instead.
- Output valid JSON only, no markdown fences, no commentary."""


def _strip_fences(content: str) -> str:
    content = content.strip()
    content = re.sub(r"^```(?:json)?\s*", "", content)
    content = re.sub(r"\s*```$", "", content)
    return content.strip()


async def generate_with_llm_stream(prompt: str):
    """Async generator that streams the LLM response.

    Yields dicts:
      {"type": "llm_status", "message": str}
      {"type": "llm_chunk", "content": str}      # main content token
      {"type": "llm_reasoning", "content": str}   # reasoning/thinking token
      {"type": "llm_error", "error": str}
      {"type": "done", "data": dict | None}       # final parsed result
    """
    if not LLM_API_KEY:
        yield {"type": "llm_error", "error": "未配置 OPENAI_API_KEY，跳过 LLM 调用"}
        yield {"type": "done", "data": None}
        return

    yield {"type": "llm_status", "message": f"正在调用大模型 {LLM_MODEL} …"}

    full_content = ""
    full_reasoning = ""
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            async with client.stream(
                "POST",
                f"{LLM_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {LLM_API_KEY}"},
                json={
                    "model": LLM_MODEL,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.7,
                    "stream": True,
                },
            ) as resp:
                if resp.status_code >= 400:
                    body = (await resp.aread()).decode("utf-8", errors="replace")
                    print(f"[agent] LLM HTTP {resp.status_code}: {body[:500]}")
                    yield {"type": "llm_error",
                           "error": f"LLM HTTP {resp.status_code}: {body[:300]}"}
                    yield {"type": "done", "data": None}
                    return

                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    choices = obj.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    reasoning = delta.get("reasoning_content") or delta.get("reasoning") or ""
                    if reasoning:
                        full_reasoning += reasoning
                        yield {"type": "llm_reasoning", "content": reasoning}
                    content = delta.get("content") or ""
                    if content:
                        full_content += content
                        yield {"type": "llm_chunk", "content": content}
    except httpx.TimeoutException:
        print("[agent] LLM request timed out")
        yield {"type": "llm_error", "error": "LLM 请求超时"}
        yield {"type": "done", "data": None}
        return
    except Exception as e:
        print(f"[agent] LLM stream failed: {e}")
        yield {"type": "llm_error", "error": f"LLM 调用失败: {e}"}
        yield {"type": "done", "data": None}
        return

    content_to_parse = full_content.strip()
    if not content_to_parse:
        print("[agent] LLM returned empty content")
        yield {"type": "llm_error", "error": "LLM 返回内容为空"}
        yield {"type": "done", "data": None}
        return

    content_to_parse = _strip_fences(content_to_parse)
    try:
        data = json.loads(content_to_parse)
    except json.JSONDecodeError as e:
        print(f"[agent] LLM JSON parse failed: {e}; content[:200]={content_to_parse[:200]!r}")
        yield {"type": "llm_error", "error": f"LLM 输出 JSON 解析失败: {e}"}
        yield {"type": "done", "data": None}
        return

    if "files" in data and "index.html" in data["files"]:
        yield {"type": "done", "data": data}
        return

    print("[agent] LLM response missing files/index.html")
    yield {"type": "llm_error", "error": "LLM 输出缺少 files.index.html"}
    yield {"type": "done", "data": None}


async def generate_with_llm(prompt: str) -> dict:
    """Non-streaming wrapper kept for compatibility."""
    result = None
    async for evt in generate_with_llm_stream(prompt):
        if evt["type"] == "done":
            result = evt["data"]
            break
    return result


# ---------- Template fallback generator ----------

PALETTES = [
    {"bg": "#0f172a", "bg2": "#1e293b", "accent": "#6366f1", "accent2": "#ec4899", "text": "#f1f5f9", "muted": "#94a3b8"},
    {"bg": "#fdf6e3", "bg2": "#fff7ed", "accent": "#ea580c", "accent2": "#d97706", "text": "#1c1917", "muted": "#78716c"},
    {"bg": "#064e3b", "bg2": "#065f46", "accent": "#34d399", "accent2": "#22d3ee", "text": "#ecfdf5", "muted": "#a7f3d0"},
    {"bg": "#1e1b4b", "bg2": "#312e81", "accent": "#a78bfa", "accent2": "#f0abfc", "text": "#ede9fe", "muted": "#c4b5fd"},
    {"bg": "#fafafa", "bg2": "#ffffff", "accent": "#2563eb", "accent2": "#7c3aed", "text": "#0f172a", "muted": "#64748b"},
]


def _detect_type(prompt: str) -> str:
    p = prompt.lower()
    if any(k in p for k in ["portfolio", "resume", "cv", "个人主页", "简历"]):
        return "portfolio"
    if any(k in p for k in ["shop", "store", "product", "商品", "商城", "卖"]):
        return "shop"
    if any(k in p for k in ["landing", "saas", "app", "产品", "创业", "launch"]):
        return "landing"
    if any(k in p for k in ["blog", "文章", "博客", "news"]):
        return "blog"
    if any(k in p for k in ["restaurant", "cafe", "menu", "餐厅", "咖啡", "菜单"]):
        return "restaurant"
    return "landing"


def _extract_name(prompt: str) -> str:
    m = re.search(r"[\"'‘’“”]([^\"'‘’“”]{2,30})[\"'‘’“”]", prompt)
    if m:
        return m.group(1)
    m = re.search(r"(?:我叫|my name is|called|名字是)\s*([A-Za-z\u4e00-\u9fa5]{2,20})", prompt, re.I)
    if m:
        return m.group(1)
    m = re.search(r"^([A-Z][a-z]{2,15})$", prompt.strip())
    if m:
        return m.group(1)
    return None


def generate_template(prompt: str) -> dict:
    ptype = _detect_type(prompt)
    pal = random.choice(PALETTES)
    name = _extract_name(prompt) or "Alex"
    title = name if ptype == "portfolio" else (prompt[:40].strip() or "My Site")

    if ptype == "portfolio":
        html = portfolio_html(name, prompt, pal)
    elif ptype == "shop":
        html = shop_html(name, prompt, pal)
    elif ptype == "restaurant":
        html = restaurant_html(name, prompt, pal)
    elif ptype == "blog":
        html = blog_html(name, prompt, pal)
    else:
        html = landing_html(name, prompt, pal)

    return {"title": title, "files": {"index.html": html}}


def base_css(pal) -> str:
    return f"""
:root {{
  --bg:{pal['bg']}; --bg2:{pal['bg2']}; --accent:{pal['accent']};
  --accent2:{pal['accent2']}; --text:{pal['text']}; --muted:{pal['muted']};
}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;background:linear-gradient(135deg,var(--bg),var(--bg2));color:var(--text);line-height:1.6;min-height:100vh}}
a{{color:var(--accent);text-decoration:none}}
h1,h2,h3{{line-height:1.2}}
.btn{{display:inline-block;padding:.85rem 1.6rem;background:linear-gradient(135deg,var(--accent),var(--accent2));color:#fff;border:none;border-radius:999px;font-weight:600;cursor:pointer;transition:transform .2s,box-shadow .2s}}
.btn:hover{{transform:translateY(-2px);box-shadow:0 10px 30px rgba(99,102,241,.4)}}
.container{{max-width:1100px;margin:0 auto;padding:0 1.5rem}}
.gradient-text{{background:linear-gradient(135deg,var(--accent),var(--accent2));-webkit-background-clip:text;background-clip:text;color:transparent}}
"""


def portfolio_html(name, prompt, pal) -> str:
    return f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{name} — Portfolio</title>
<style>{base_css(pal)}
.hero{{min-height:100vh;display:flex;align-items:center;text-align:center;padding:4rem 1rem}}
.hero h1{{font-size:clamp(2.5rem,7vw,5rem);margin-bottom:1rem}}
.hero p{{font-size:1.2rem;color:var(--muted);max-width:600px;margin:0 auto 2rem}}
.avatar{{width:120px;height:120px;border-radius:50%;background:linear-gradient(135deg,var(--accent),var(--accent2));margin:0 auto 2rem;display:flex;align-items:center;justify-content:center;font-size:3rem;font-weight:800}}
section{{padding:5rem 1rem}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:1.5rem}}
.card{{background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.1);border-radius:1rem;padding:1.5rem;backdrop-filter:blur(8px)}}
.card h3{{margin-bottom:.5rem;color:var(--accent)}}
.skills{{display:flex;flex-wrap:wrap;gap:.5rem;margin-top:1rem}}
.tag{{padding:.3rem .8rem;background:rgba(99,102,241,.15);border-radius:999px;font-size:.85rem}}
</style></head><body>
<header class="hero"><div class="container">
  <div class="avatar">{name[0].upper()}</div>
  <h1>Hi, I'm <span class="gradient-text">{name}</span></h1>
  <p>{prompt}</p>
  <a href="#work" class="btn">查看作品</a>
</div></header>
<section id="work"><div class="container">
  <h2 class="gradient-text" style="margin-bottom:2rem;font-size:2rem">作品</h2>
  <div class="grid">
    <div class="card"><h3>项目一</h3><p>一个充满创意的全栈项目，结合现代设计与流畅交互。</p></div>
    <div class="card"><h3>项目二</h3><p>专注用户体验的移动优先应用，性能优异。</p></div>
    <div class="card"><h3>项目三</h3><p>数据可视化仪表盘，将复杂信息优雅呈现。</p></div>
  </div>
  <div class="skills">
    <span class="tag">React</span><span class="tag">Python</span><span class="tag">设计</span>
    <span class="tag">Node.js</span><span class="tag">Cloud</span>
  </div>
</div></section>
<section style="text-align:center"><div class="container">
  <h2 class="gradient-text" style="font-size:2rem;margin-bottom:1rem">联系我</h2>
  <p style="color:var(--muted);margin-bottom:2rem">随时欢迎交流合作</p>
  <a href="mailto:hello@example.com" class="btn">发送邮件</a>
</div></section>
</body></html>"""


def landing_html(name, prompt, pal) -> str:
    return f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{name}</title>
<style>{base_css(pal)}
nav{{display:flex;justify-content:space-between;align-items:center;padding:1.5rem 0}}
.logo{{font-weight:800;font-size:1.4rem}}
.hero{{padding:6rem 1rem 4rem;text-align:center}}
.hero h1{{font-size:clamp(2.2rem,6vw,4rem);margin-bottom:1.2rem}}
.hero p{{font-size:1.15rem;color:var(--muted);max-width:640px;margin:0 auto 2rem}}
.features{{padding:4rem 1rem}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:1.5rem}}
.card{{background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.1);border-radius:1rem;padding:2rem;transition:transform .2s}}
.card:hover{{transform:translateY(-4px)}}
.icon{{width:48px;height:48px;border-radius:12px;background:linear-gradient(135deg,var(--accent),var(--accent2));margin-bottom:1rem;display:flex;align-items:center;justify-content:center;font-size:1.5rem}}
.cta{{padding:5rem 1rem;text-align:center}}
</style></head><body>
<div class="container"><nav><div class="logo gradient-text">{name}</div><a href="#cta" class="btn">开始使用</a></nav></div>
<header class="hero"><div class="container">
  <h1><span class="gradient-text">{prompt[:80]}</span></h1>
  <p>用最简单的方式，把你的想法变成现实。快速、美观、可靠。</p>
  <a href="#cta" class="btn">免费体验 →</a>
</div></header>
<section class="features"><div class="container"><div class="grid">
  <div class="card"><div class="icon">⚡</div><h3>极速</h3><p style="color:var(--muted)">毫秒级响应，全球 CDN 加速。</p></div>
  <div class="card"><div class="icon">🎨</div><h3>美观</h3><p style="color:var(--muted)">现代设计语言，细节打磨到位。</p></div>
  <div class="card"><div class="icon">🔒</div><h3>安全</h3><p style="color:var(--muted)">企业级安全，数据加密存储。</p></div>
</div></div></section>
<section id="cta" class="cta"><div class="container">
  <h2 class="gradient-text" style="font-size:2.2rem;margin-bottom:1rem">准备好了吗？</h2>
  <p style="color:var(--muted);margin-bottom:2rem">立即开始，几分钟内拥有你的专属网站。</p>
  <a href="#" class="btn">立即注册</a>
</div></section>
</body></html>"""


def shop_html(name, prompt, pal) -> str:
    items = [
        ("经典款", "¥199", "百搭舒适"),
        ("限量版", "¥399", "匠心工艺"),
        ("新品", "¥259", "限时优惠"),
        ("套装", "¥599", "超值组合"),
    ]
    cards = "".join(
        f'<div class="card"><div class="img" style="background:linear-gradient(135deg,var(--accent),var(--accent2))"></div><h3>{n}</h3><p style="color:var(--muted)">{d}</p><p style="font-size:1.3rem;font-weight:700;color:var(--accent)">{p}</p><button class="btn" style="margin-top:.5rem">加入购物车</button></div>'
        for n, p, d in items
    )
    return f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{name} — Shop</title>
<style>{base_css(pal)}
.hero{{text-align:center;padding:5rem 1rem 2rem}}
.hero h1{{font-size:clamp(2rem,5vw,3.5rem)}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:1.5rem;padding:2rem 1rem 5rem}}
.card{{background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.1);border-radius:1rem;padding:1.5rem;text-align:center}}
.img{{height:160px;border-radius:.75rem;margin-bottom:1rem}}
</style></head><body>
<header class="hero"><div class="container">
  <h1 class="gradient-text">{name} Store</h1>
  <p style="color:var(--muted);margin-top:1rem">{prompt}</p>
</div></header>
<section><div class="container"><div class="grid">{cards}</div></div></section>
</body></html>"""


def restaurant_html(name, prompt, pal) -> str:
    dishes = [
        ("招牌牛排", "¥168", "精选谷饲，外焦里嫩"),
        ("奶油意面", "¥58", "浓郁奶香，经典风味"),
        ("凯撒沙拉", "¥38", "新鲜时蔬，清爽开胃"),
        ("提拉米苏", "¥42", "意式经典，绵密细腻"),
    ]
    rows = "".join(f'<div class="dish"><div><h4>{n}</h4><p style="color:var(--muted);font-size:.9rem">{d}</p></div><span>{p}</span></div>' for n, p, d in dishes)
    return f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{name} — 餐厅</title>
<style>{base_css(pal)}
.hero{{text-align:center;padding:5rem 1rem 2rem}}
.hero h1{{font-size:clamp(2.2rem,5vw,3.5rem)}}
.menu{{max-width:600px;margin:2rem auto;padding:2rem 1rem 5rem}}
.dish{{display:flex;justify-content:space-between;align-items:center;padding:1.2rem 0;border-bottom:1px solid rgba(255,255,255,.1)}}
.dish span{{font-weight:700;color:var(--accent)}}
</style></head><body>
<header class="hero"><div class="container">
  <h1 class="gradient-text">{name}</h1>
  <p style="color:var(--muted);margin-top:1rem">{prompt}</p>
</div></header>
<section class="menu"><div class="container">{rows}</div></section>
</body></html>"""


def blog_html(name, prompt, pal) -> str:
    posts = [
        ("开始写博客的第一天", "记录下这个新旅程的起点与期待。"),
        ("关于设计的思考", "好的设计是看不见的，它让一切自然发生。"),
        ("效率工具分享", "这些工具让我的工作流更顺畅。"),
    ]
    items = "".join(f'<article class="card"><h3>{t}</h3><p style="color:var(--muted)">{d}</p><a href="#">阅读全文 →</a></article>' for t, d in posts)
    return f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{name} — Blog</title>
<style>{base_css(pal)}
header{{text-align:center;padding:4rem 1rem 2rem}}
header h1{{font-size:clamp(2rem,5vw,3rem)}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:1.5rem;padding:2rem 1rem 5rem}}
.card{{background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.1);border-radius:1rem;padding:2rem}}
.card h3{{margin-bottom:.5rem}}
.card a{{display:inline-block;margin-top:1rem;font-weight:600}}
</style></head><body>
<header><div class="container"><h1 class="gradient-text">{name}'s Blog</h1><p style="color:var(--muted);margin-top:1rem">{prompt}</p></div></header>
<section><div class="container"><div class="grid">{items}</div></div></section>
</body></html>"""


async def generate_site_stream(prompt: str):
    """Async generator that yields LLM thinking events and finally the result.

    Yields the same event types as ``generate_with_llm_stream`` plus a final
    ``{"type": "done", "data": {...}}`` carrying the chosen site (LLM or
    template fallback).
    """
    used_template = False
    if LLM_API_KEY:
        async for evt in generate_with_llm_stream(prompt):
            if evt["type"] == "done":
                if evt["data"] is not None:
                    yield evt
                    return
            else:
                yield evt
    else:
        yield {"type": "llm_error", "error": "未配置 OPENAI_API_KEY，使用模板生成"}

    used_template = True
    yield {"type": "llm_status", "message": "使用内置模板生成网站…"}
    await asyncio.sleep(0.5)
    result = generate_template(prompt)
    if used_template:
        yield {"type": "llm_status", "message": "模板生成完成"}
    yield {"type": "done", "data": result}


async def generate_site(prompt: str) -> dict:
    """Return {title, files}. Tries LLM first, then template fallback."""
    result = None
    async for evt in generate_site_stream(prompt):
        if evt["type"] == "done":
            result = evt["data"]
            break
    return result
