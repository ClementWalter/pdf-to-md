"""HTML landing page for unpdf.it.

Serves a polished single-page site with try-it-live demo, output sample,
agent skill installation instructions, pricing, and trust signals.
"""


def render_landing(domain: str) -> str:
    """Return the full HTML landing page with the given domain baked in."""
    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>unpdf.it — PDF to Markdown API</title>
<meta name="description" content="Convert any PDF to clean markdown. One URL rewrite. Free API for AI agents, developers, and LLMs.">
<style>
  :root {{
    --bg: #0a0a0a;
    --card: #141414;
    --border: #262626;
    --text: #e5e5e5;
    --muted: #737373;
    --accent: #3b82f6;
    --accent-hover: #2563eb;
    --green: #22c55e;
    --mono: 'SF Mono', 'Cascadia Code', 'Fira Code', Consolas, monospace;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
  }}
  .container {{ max-width: 720px; margin: 0 auto; padding: 0 24px; }}

  /* Hero */
  .hero {{
    text-align: center;
    padding: 80px 0 48px;
  }}
  .hero h1 {{
    font-size: 3rem;
    font-weight: 700;
    letter-spacing: -0.03em;
    margin-bottom: 12px;
  }}
  .hero h1 span {{ color: var(--accent); }}
  .hero p {{
    font-size: 1.25rem;
    color: var(--muted);
    max-width: 480px;
    margin: 0 auto;
  }}

  /* Try it */
  .try-it {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 24px;
    margin-bottom: 48px;
  }}
  .try-it label {{
    display: block;
    font-size: 0.875rem;
    color: var(--muted);
    margin-bottom: 8px;
  }}
  .input-row {{
    display: flex;
    gap: 8px;
  }}
  .input-row input {{
    flex: 1;
    padding: 10px 14px;
    font-size: 0.95rem;
    font-family: var(--mono);
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 8px;
    color: var(--text);
    outline: none;
  }}
  .input-row input:focus {{ border-color: var(--accent); }}
  .input-row button {{
    padding: 10px 20px;
    font-size: 0.95rem;
    font-weight: 600;
    background: var(--accent);
    color: #fff;
    border: none;
    border-radius: 8px;
    cursor: pointer;
    white-space: nowrap;
  }}
  .input-row button:hover {{ background: var(--accent-hover); }}
  .input-row button:disabled {{ opacity: 0.5; cursor: wait; }}
  #result {{
    margin-top: 16px;
    display: none;
  }}
  #result pre {{
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px;
    font-family: var(--mono);
    font-size: 0.85rem;
    overflow-x: auto;
    max-height: 300px;
    overflow-y: auto;
    white-space: pre-wrap;
    word-break: break-word;
  }}
  #result .meta {{
    font-size: 0.8rem;
    color: var(--muted);
    margin-top: 8px;
  }}

  /* Sample */
  .sample {{
    margin-bottom: 48px;
  }}
  .sample h2 {{ font-size: 1rem; color: var(--muted); margin-bottom: 12px; text-transform: uppercase; letter-spacing: 0.05em; }}
  .sample .url {{
    font-family: var(--mono);
    font-size: 0.85rem;
    color: var(--accent);
    word-break: break-all;
    display: block;
    margin-bottom: 12px;
  }}
  .sample pre {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px;
    font-family: var(--mono);
    font-size: 0.85rem;
    overflow-x: auto;
    white-space: pre-wrap;
  }}

  /* Sections */
  section {{ margin-bottom: 48px; }}
  section h2 {{
    font-size: 1.5rem;
    font-weight: 600;
    margin-bottom: 16px;
    letter-spacing: -0.02em;
  }}

  /* Skill install */
  .skills-grid {{
    display: grid;
    grid-template-columns: 1fr;
    gap: 12px;
  }}
  .skill-card {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px;
  }}
  .skill-card h3 {{
    font-size: 0.95rem;
    font-weight: 600;
    margin-bottom: 8px;
  }}
  .skill-card code {{
    display: block;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 10px 12px;
    font-family: var(--mono);
    font-size: 0.8rem;
    overflow-x: auto;
    white-space: pre;
    color: var(--green);
    cursor: pointer;
    position: relative;
  }}
  .skill-card code:hover {{ border-color: var(--accent); }}
  .skill-card .note {{
    font-size: 0.8rem;
    color: var(--muted);
    margin-top: 8px;
  }}

  /* Pricing */
  .pricing-card {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 24px;
    text-align: center;
  }}
  .pricing-card .badge {{
    display: inline-block;
    background: var(--accent);
    color: #fff;
    font-size: 0.75rem;
    font-weight: 700;
    padding: 4px 10px;
    border-radius: 999px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 12px;
  }}
  .pricing-card .price {{
    font-size: 2rem;
    font-weight: 700;
  }}
  .pricing-card .limits {{
    color: var(--muted);
    font-size: 0.9rem;
    margin-top: 8px;
  }}
  .pricing-card ul {{
    list-style: none;
    text-align: left;
    margin-top: 16px;
  }}
  .pricing-card li {{
    padding: 6px 0;
    font-size: 0.9rem;
    color: var(--muted);
  }}
  .pricing-card li::before {{
    content: "\\2713";
    color: var(--green);
    margin-right: 8px;
    font-weight: 700;
  }}

  /* Footer */
  footer {{
    border-top: 1px solid var(--border);
    padding: 32px 0;
    text-align: center;
    color: var(--muted);
    font-size: 0.85rem;
  }}
  footer a {{ color: var(--accent); text-decoration: none; }}
  footer a:hover {{ text-decoration: underline; }}

  .copy-toast {{
    position: fixed;
    bottom: 24px;
    left: 50%;
    transform: translateX(-50%);
    background: var(--green);
    color: #000;
    padding: 8px 16px;
    border-radius: 8px;
    font-size: 0.85rem;
    font-weight: 600;
    opacity: 0;
    transition: opacity 0.3s;
    pointer-events: none;
  }}
  .copy-toast.show {{ opacity: 1; }}
</style>
</head>
<body>

<div class="container">
  <div class="hero">
    <h1>un<span>pdf</span>.it</h1>
    <p>Convert any PDF to clean markdown. One URL rewrite. Built for AI agents.</p>
  </div>

  <div class="try-it">
    <label>Paste a PDF URL and hit Convert</label>
    <div class="input-row">
      <input type="text" id="pdfUrl" placeholder="https://arxiv.org/pdf/2301.00001v1.pdf" value="https://arxiv.org/pdf/2301.00001v1.pdf">
      <button id="convertBtn" onclick="convert()">Convert</button>
    </div>
    <div id="result">
      <pre id="output"></pre>
      <div class="meta" id="meta"></div>
    </div>
  </div>

  <div class="sample">
    <h2>Output sample</h2>
    <span class="url">GET https://{domain}/arxiv.org/pdf/2301.00001v1.pdf</span>
    <pre>## **NFTrig: Using Blockchain Technologies for Math Education**

JORDAN THOMPSON, Augustana College, USA
RYAN BENAC, Augustana College, USA

NFTrig is a web-based application created for use as an
educational tool to teach trigonometry and blockchain
technology. Creation of the application includes front
and back end development as well as integration with
other outside sources including MetaMask and OpenSea...</pre>
  </div>

  <section>
    <h2>Add to your AI agent</h2>
    <p style="color: var(--muted); margin-bottom: 16px;">
      unpdf.it follows the <a href="https://agentskills.io" style="color: var(--accent); text-decoration: none;">Agent Skills</a> open standard.
      One install, and your agent reads PDFs as markdown automatically.
    </p>
    <div class="skills-grid">
      <div class="skill-card">
        <h3>Claude Code</h3>
        <code onclick="copyCode(this)">mkdir -p ~/.claude/skills/unpdf && curl -s https://{domain}/skill > ~/.claude/skills/unpdf/SKILL.md</code>
      </div>
      <div class="skill-card">
        <h3>Cursor</h3>
        <code onclick="copyCode(this)">mkdir -p .cursor/skills/unpdf && curl -s https://{domain}/skill > .cursor/skills/unpdf/SKILL.md</code>
      </div>
      <div class="skill-card">
        <h3>Windsurf</h3>
        <code onclick="copyCode(this)">mkdir -p .windsurf/skills/unpdf && curl -s https://{domain}/skill > .windsurf/skills/unpdf/SKILL.md</code>
      </div>
      <div class="skill-card">
        <h3>GitHub Copilot</h3>
        <code onclick="copyCode(this)">mkdir -p .github/skills/unpdf && curl -s https://{domain}/skill > .github/skills/unpdf/SKILL.md</code>
      </div>
      <div class="skill-card">
        <h3>OpenClaw / Any Agent Skills compatible</h3>
        <code onclick="copyCode(this)">mkdir -p ~/.agents/skills/unpdf && curl -s https://{domain}/skill > ~/.agents/skills/unpdf/SKILL.md</code>
        <div class="note">Works with any agent that supports the Agent Skills standard.</div>
      </div>
    </div>
  </section>

  <section>
    <h2>Pricing</h2>
    <div class="pricing-card">
      <div class="badge">Beta</div>
      <div class="price">Free</div>
      <div class="limits">During the beta period</div>
      <ul>
        <li>PDFs up to 50 MB</li>
        <li>Images extracted and served</li>
        <li>Results cached for 30 days</li>
        <li>No authentication required</li>
        <li>No rate limit (fair use)</li>
      </ul>
    </div>
  </section>

  <footer>
    Built by <a href="https://github.com/ClementWalter">Clement Walter</a>
    &middot;
    <a href="https://github.com/ClementWalter/pdf-to-md">Source on GitHub</a>
    &middot;
    <a href="https://{domain}/skill">SKILL.md</a>
  </footer>
</div>

<div class="copy-toast" id="toast">Copied!</div>

<script>
async function convert() {{
  const input = document.getElementById('pdfUrl').value.trim();
  if (!input) return;
  const btn = document.getElementById('convertBtn');
  const result = document.getElementById('result');
  const output = document.getElementById('output');
  const meta = document.getElementById('meta');

  btn.disabled = true;
  btn.textContent = 'Converting...';
  result.style.display = 'block';
  output.textContent = 'Loading...';
  meta.textContent = '';

  try {{
    // Strip protocol from URL
    const url = input.replace(/^https?:\\/\\//, '');
    const start = performance.now();
    const resp = await fetch('/' + url);
    const elapsed = Math.round(performance.now() - start);
    const text = await resp.text();

    if (!resp.ok) {{
      output.textContent = text;
      meta.textContent = 'Error ' + resp.status;
    }} else {{
      // Show first 1500 chars
      output.textContent = text.length > 1500 ? text.slice(0, 1500) + '\\n\\n[... truncated ...]' : text;
      const pages = resp.headers.get('X-Page-Count') || '?';
      const cached = resp.headers.get('X-Cached') === 'true';
      meta.textContent = pages + ' pages \\u00b7 ' + (cached ? 'cached' : elapsed + 'ms') + ' \\u00b7 ' + (text.length / 1024).toFixed(1) + ' KB markdown';
    }}
  }} catch (e) {{
    output.textContent = 'Error: ' + e.message;
  }}
  btn.disabled = false;
  btn.textContent = 'Convert';
}}

function copyCode(el) {{
  navigator.clipboard.writeText(el.textContent);
  const toast = document.getElementById('toast');
  toast.classList.add('show');
  setTimeout(() => toast.classList.remove('show'), 1500);
}}
</script>
</body>
</html>"""
