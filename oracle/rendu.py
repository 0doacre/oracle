"""Le point (Markdown restreint, écrit par point_matinal) en HTML, pour le mail et la
page web. Seules les formes qu'il produit sont gérées : titres #, ##, ###, puces
« - », citations « > », filet « --- », **gras** et *italique*. Tout le texte est
échappé avant mise en forme : un intitulé de marché ne peut pas injecter de HTML."""

import html
import re

STYLE = """
body{margin:0;padding:24px 16px;background:#f6f5f1;color:#1c1c1a;
 font:15px/1.5 -apple-system,'Segoe UI',system-ui,sans-serif}
main{max-width:760px;margin:0 auto;background:#fff;border:1px solid #e3e1da;
 border-radius:10px;padding:20px 22px}
h1{font-size:21px;margin:0 0 12px}h2{font-size:17px;margin:22px 0 8px}
h3{font-size:15px;margin:16px 0 6px;color:#2f5d8a}ul{padding-left:20px;margin:6px 0}
li{margin:5px 0}blockquote{margin:10px 0;padding:8px 12px;background:#fff4e0;
 border-left:3px solid #b06a00;border-radius:6px}em{color:#6b6a64}
hr{border:0;border-top:1px solid #e3e1da;margin:18px 0}a{color:#2f5d8a}
@media (prefers-color-scheme:dark){body{background:#121314;color:#e8e6e1}
 main{background:#1b1d1f;border-color:#2c2f32}h3,a{color:#7fb0e0}em{color:#9a988f}
 blockquote{background:#2e2412}hr{border-top-color:#2c2f32}}
"""


def _en_ligne(texte: str) -> str:
    texte = html.escape(texte, quote=False)
    texte = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", texte)
    return re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", texte)


def markdown_vers_html(texte: str) -> str:
    """Le corps HTML (sans <html>) du Markdown restreint."""
    sortie, dans_liste = [], False
    for ligne in texte.splitlines():
        ligne = ligne.rstrip()
        est_puce = ligne.startswith("- ")
        if dans_liste and not est_puce:
            sortie.append("</ul>")
            dans_liste = False
        if est_puce:
            if not dans_liste:
                sortie.append("<ul>")
                dans_liste = True
            sortie.append(f"<li>{_en_ligne(ligne[2:])}</li>")
        elif m := re.match(r"(#{1,3}) (.*)", ligne):
            n = len(m.group(1))
            sortie.append(f"<h{n}>{_en_ligne(m.group(2))}</h{n}>")
        elif ligne.startswith("> "):
            sortie.append(f"<blockquote>{_en_ligne(ligne[2:])}</blockquote>")
        elif ligne == "---":
            sortie.append("<hr>")
        elif ligne:
            sortie.append(f"<p>{_en_ligne(ligne)}</p>")
    if dans_liste:
        sortie.append("</ul>")
    return "\n".join(sortie)


def page(texte_markdown: str, titre: str, pied_html: str = "") -> str:
    """Une page HTML complète, autonome (styles en ligne : lisible dans un mail)."""
    return (f"<!doctype html><html lang=\"fr\"><head><meta charset=\"utf-8\">"
            f"<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            f"<title>{html.escape(titre)}</title><style>{STYLE}</style></head>"
            f"<body><main>{markdown_vers_html(texte_markdown)}{pied_html}</main></body></html>")
