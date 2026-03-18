"""
Module d'export Excel avec mise en forme couleur par onglet.
"""

import io
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
from openpyxl.utils import get_column_letter


# Couleurs
CLR_VERT = "1E7E34"
CLR_ROUGE = "C0392B"
CLR_ORANGE = "E67E22"
CLR_BLEU_HEADER = "1F4E79"
CLR_GRIS = "F2F2F2"
CLR_BLANC = "FFFFFF"


def _fill(hex_color):
    return PatternFill(start_color=hex_color, end_color=hex_color, fill_type="solid")


def _font(bold=False, color="000000", size=10):
    return Font(bold=bold, color=color, size=size)


def _border():
    side = Side(style="thin", color="BFBFBF")
    return Border(left=side, right=side, top=side, bottom=side)


def _write_header_row(ws, headers, row, bg_color=CLR_BLEU_HEADER, font_color="FFFFFF"):
    for col_idx, h in enumerate(headers, 1):
        cell = ws.cell(row=row, column=col_idx, value=h)
        cell.fill = _fill(bg_color)
        cell.font = _font(bold=True, color=font_color)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = _border()


# Couleurs qui nécessitent du texte blanc
_DARK_BG = {CLR_VERT, CLR_ROUGE, CLR_ORANGE, CLR_BLEU_HEADER}

def _write_data_row(ws, values, row, bg_color=CLR_BLANC):
    font_color = "FFFFFF" if bg_color in _DARK_BG else "000000"
    for col_idx, v in enumerate(values, 1):
        cell = ws.cell(row=row, column=col_idx, value=v)
        cell.fill = _fill(bg_color)
        cell.font = _font(bold=(bg_color in _DARK_BG), color=font_color)
        cell.alignment = Alignment(vertical="center")
        cell.border = _border()


def _auto_width(ws, min_w=12, max_w=40):
    for col in ws.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            try:
                if cell.value:
                    max_len = max(max_len, len(str(cell.value)))
            except Exception:
                pass
        ws.column_dimensions[col_letter].width = min(max_w, max(min_w, max_len + 2))


def generer_excel(results: dict, jour: str) -> bytes:
    """
    Génère le fichier Excel complet à partir des résultats croisés.
    Retourne les bytes du fichier .xlsx
    """
    wb = Workbook()
    wb.remove(wb.active)  # Supprimer la feuille vide par défaut

    # ---- Onglet RÉCAPITULATIF ----
    ws_recap = wb.create_sheet("Récapitulatif")
    ws_recap.freeze_panes = "A2"
    headers_recap = ["Réappro", "Prévues", "Faites", "Non Faites", "Jokers", "Taux (%)"]
    _write_header_row(ws_recap, headers_recap, 1)

    row = 2
    for reappro, data in sorted(results.items()):
        nb_prev = len(data["salles_prevues"])
        nb_fait = len(data["salles_faites"])
        nb_nf = len(data["salles_non_faites"])
        nb_joker = sum(1 for s in data["salles_faites"] if s["is_joker"])
        taux = round((nb_fait / nb_prev * 100) if nb_prev > 0 else 0, 1)

        if nb_nf == 0:
            bg = CLR_VERT
        elif nb_nf == nb_prev:
            bg = CLR_ROUGE
        else:
            bg = CLR_ORANGE

        _write_data_row(ws_recap, [reappro, nb_prev, nb_fait, nb_nf, nb_joker, f"{taux}%"], row, bg)
        row += 1

    _auto_width(ws_recap)

    # ---- Onglet SALLES NON FAITES ----
    ws_nf = wb.create_sheet("Salles Non Faites")
    ws_nf.freeze_panes = "A2"
    headers_nf = ["Réappro", "Client / Salle", "Machine ID"]
    _write_header_row(ws_nf, headers_nf, 1)

    row = 2
    for reappro, data in sorted(results.items()):
        for s in data["salles_non_faites"]:
            _write_data_row(ws_nf, [reappro, s["client"], s["machine"]], row, CLR_ROUGE)
            row += 1

    if row == 2:
        ws_nf.cell(row=2, column=1, value="✅ Toutes les salles ont été faites !")
    _auto_width(ws_nf)

    # ---- Onglet JOKERS ----
    ws_joker = wb.create_sheet("Jokers - Remplacements")
    ws_joker.freeze_panes = "A2"
    headers_j = ["Réappro Prévu", "Client / Salle", "Machine ID", "Fait Par", "Valeur Ref"]
    _write_header_row(ws_joker, headers_j, 1)

    row = 2
    for reappro, data in sorted(results.items()):
        for s in data["salles_faites"]:
            if s["is_joker"]:
                _write_data_row(
                    ws_joker,
                    [reappro, s["client"], s["machine"], s["employe_reel"], s["val_ref"]],
                    row,
                    CLR_ORANGE,
                )
                row += 1

    if row == 2:
        ws_joker.cell(row=2, column=1, value="Aucun remplacement (joker) détecté.")
    _auto_width(ws_joker)

    # ---- Un onglet par réappro ----
    headers_detail = ["Client / Salle", "Machine ID", "Statut", "Fait Par", "Valeur Ref"]

    for reappro, data in sorted(results.items()):
        safe_name = reappro[:31]
        ws = wb.create_sheet(safe_name)
        ws.freeze_panes = "A5"

        nb_prev = len(data["salles_prevues"])
        nb_fait = len(data["salles_faites"])
        nb_nf = len(data["salles_non_faites"])
        nb_joker = sum(1 for s in data["salles_faites"] if s["is_joker"])
        taux = round((nb_fait / nb_prev * 100) if nb_prev > 0 else 0, 1)

        # Mini résumé (lignes 1-3)
        ws.merge_cells("A1:E1")
        title_cell = ws["A1"]
        title_cell.value = f"📋 {reappro} — {jour}"
        title_cell.font = _font(bold=True, color="1F4E79", size=13)
        title_cell.alignment = Alignment(horizontal="center")

        ws.merge_cells("A2:E2")
        taux_color = "00B050" if taux == 100 else ("FF0000" if taux == 0 else "FF6600")
        resume_cell = ws["A2"]
        resume_cell.value = (
            f"Prévues: {nb_prev}   |   Faites: {nb_fait}   |   "
            f"Non Faites: {nb_nf}   |   Jokers: {nb_joker}   |   Taux: {taux}%"
        )
        resume_cell.font = _font(bold=True, color=taux_color, size=11)
        resume_cell.alignment = Alignment(horizontal="center")

        ws.row_dimensions[3].height = 6  # Séparation visuelle

        # Header
        _write_header_row(ws, headers_detail, 4)

        row = 5
        # Non faites en premier (rouge)
        for s in data["salles_non_faites"]:
            _write_data_row(ws, [s["client"], s["machine"], "❌ Non Faite", "", ""], row, CLR_ROUGE)
            row += 1

        # Jokers (orange)
        for s in data["salles_faites"]:
            if s["is_joker"]:
                _write_data_row(
                    ws,
                    [s["client"], s["machine"], f"🔄 Joker ({s['statut']})", s["employe_reel"], s["val_ref"]],
                    row,
                    CLR_ORANGE,
                )
                row += 1

        # Faites normalement (vert)
        for s in data["salles_faites"]:
            if not s["is_joker"]:
                _write_data_row(
                    ws,
                    [s["client"], s["machine"], f"✅ Fait ({s['statut']})", s["employe_reel"], s["val_ref"]],
                    row,
                    CLR_VERT,
                )
                row += 1

        _auto_width(ws)

    # Sauvegarder en mémoire
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer.read()
