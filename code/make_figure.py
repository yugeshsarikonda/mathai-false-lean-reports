#!/usr/bin/env python3
"""Recreate Figure 1 (three panels) from the retained trial records.

(a) Original batch, initial decisions: no report against fabricated report for the three arms.
    The first two rows pool all three Claude models; the third is the balanced Opus and Haiku
    insufficient rfl comparison (18/26 against 5/26).
(b) Later batch, Opus and Haiku pooled: correct initial decisions next to correct final
    submissions, for general working proofs and for closed decide instances, without a report
    and under a fabricated error.
(c) Later batch, insufficient rfl proofs under fabricated success: correct revisions per model
    without provenance, with the matching recent block and with the mismatched older block.

Every plotted count is recomputed from data/original and data/rescored and asserted against the
saved reference counts. Writes fig1_final.png into figures/.
"""
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
import pandas as pd
from statsmodels.stats.proportion import proportion_confint

ROOT = Path(__file__).resolve().parents[1]
OP, HK, SN = 'claude-opus-4-5-20251101', 'claude-haiku-4-5-20251001', 'claude-sonnet-5'
BLUE, RUST, GREY = '#385D78', '#B75532', '#8A8F98'


def truth(s):
    return s.astype(str).str.lower().isin(['true', '1', '1.0'])


def wilson(k, n):
    lo, hi = proportion_confint(k, n, method='wilson')
    return 100 * lo, 100 * hi


# ---- data ---------------------------------------------------------------------------------
g = pd.read_csv(ROOT / 'data/original/hardened_grid.csv')
m = pd.read_csv(ROOT / 'data/original/mechanism_cell.csv')
rc = pd.read_csv(ROOT / 'data/rescored/claude.csv')

DEC = ['KEEP', 'REVISE', 'REJECT_UNPROVABLE']
panel_a = []
for df, a, b, decision in [(g, 'NT_broken', 'FV_broken', 'REJECT_UNPROVABLE'),
                           (g, 'NT_valid', 'FV_valid', 'KEEP'),
                           (m[m.model.isin([OP, HK])], 'TWT_notool', 'TWT_fake_success', 'REVISE')]:
    pair = []
    for c in (a, b):
        z = df[(df.cell == c) & df.dec.isin(DEC)]
        pair.append((int((z.dec == decision).sum()), len(z)))
    panel_a.append(pair)
assert panel_a == [[(37, 42), (35, 41)], [(40, 42), (2, 41)], [(18, 26), (5, 26)]], panel_a

oh = rc[rc.model.isin([OP, HK])]


def cell(df, c):
    z = df[df.cell == c]
    return int(truth(z.dec_correct).sum()), int(truth(z.outcome_correct).sum()), len(z)


panel_b = {c: cell(oh, c) for c in ['OMG_notool', 'OMG_FE', 'DEC_notool', 'DEC_FE']}
assert panel_b == {'OMG_notool': (27, 28, 28), 'OMG_FE': (1, 20, 28),
                   'DEC_notool': (24, 27, 28), 'DEC_FE': (5, 12, 28)}, panel_b

panel_c = {name: {c: cell(rc[rc.model == mod], c)
                  for c in ['RFL_FS', 'RFL_FS_prov_match', 'RFL_FS_prov_mismatch']}
           for mod, name in [(OP, 'Opus'), (HK, 'Haiku')]}
assert [panel_c['Opus'][c][0] for c in panel_c['Opus']] == [0, 6, 13]
assert [panel_c['Haiku'][c][0] for c in panel_c['Haiku']] == [5, 1, 0]

# ---- style --------------------------------------------------------------------------------
plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 7, 'axes.titlesize': 7,
                     'axes.labelsize': 7, 'xtick.labelsize': 6, 'ytick.labelsize': 6,
                     'legend.fontsize': 6, 'axes.spines.top': False, 'axes.spines.right': False,
                     'axes.linewidth': 0.7})
fig = plt.figure(figsize=(5.5, 3.3))
gs = fig.add_gridspec(2, 2, height_ratios=[0.95, 1.25], width_ratios=[1.05, 0.95], hspace=0.95, wspace=0.42,
                      left=0.185, right=0.985, bottom=0.16, top=0.90)
axes = [fig.add_subplot(gs[0, :]), fig.add_subplot(gs[1, 0]), fig.add_subplot(gs[1, 1])]


def letter(ax, s):
    ax.text(-0.02, 1.22, s, transform=ax.transAxes, fontweight='bold', fontsize=8, va='bottom', ha='right')


# (a) dot plot, original batch
ax = axes[0]
rows = ['False statement\nreference: reject', 'Working proof\nreference: keep', 'Insufficient rfl\nreference: revise']
for j, (name, marker, col) in enumerate([('No report', 'o', BLUE), ('Fabricated report', 'D', RUST)]):
    for i, pair in enumerate(panel_a):
        k, n = pair[j]
        y = 2 - i + (0.2 if j == 0 else -0.2)
        v = 100 * k / n
        lo, hi = wilson(k, n)
        ax.errorbar(v, y, xerr=[[v - lo], [hi - v]], fmt=marker, color=col, capsize=2, ms=4, lw=0.9)
        side = 8 if v < 60 else -8
        ax.annotate(f'{k}/{n}', (hi if v < 60 else lo, y), xytext=(side, 0), textcoords='offset points',
                    ha='left' if v < 60 else 'right', va='center', fontsize=5.5, color=col)
ax.set_yticks([2, 1, 0], rows)
ax.tick_params(axis='y', length=0, pad=6)
ax.set_xlim(-4, 104); ax.set_ylim(-0.55, 2.55); ax.set_xticks([0, 25, 50, 75, 100])
ax.set_xlabel('Correct initial decisions (%)')
ax.grid(axis='x', color='#e3e3e3', lw=0.6); ax.set_axisbelow(True); ax.spines['left'].set_visible(False)
ax.set_title('Original batch, initial decisions', loc='left', pad=4)
ax.legend(handles=[Line2D([], [], marker='o', color=BLUE, ls='', ms=4, label='No report'),
                   Line2D([], [], marker='D', color=RUST, ls='', ms=4, label='Fabricated report')],
          loc='lower right', bbox_to_anchor=(1.0, 1.02), ncol=2, frameon=False, handlelength=1.0,
          borderaxespad=0.0, columnspacing=1.2)
letter(ax, 'a')

# (b) grouped bars, initial vs final, Opus + Haiku
ax = axes[1]
order = [('OMG_notool', 'no report'), ('OMG_FE', 'fabricated\nerror'), ('DEC_notool', 'no report'), ('DEC_FE', 'fabricated\nerror')]
x = [0, 1, 2.5, 3.5]
w = 0.38
for xi, (c, lab) in zip(x, order):
    init, fin, n = panel_b[c]
    ax.bar(xi - w / 2, 100 * init / n, w, color=BLUE, label='Initial decision' if xi == 0 else None)
    ax.bar(xi + w / 2, 100 * fin / n, w, color=BLUE, alpha=0.35, hatch='///', edgecolor=BLUE, lw=0,
           label='Final submission' if xi == 0 else None)
    ax.text(xi - w / 2, 100 * init / n + 2, f'{init}', ha='center', fontsize=5.5, color=BLUE)
    ax.text(xi + w / 2, 100 * fin / n + 2, f'{fin}', ha='center', fontsize=5.5, color=BLUE)
ax.set_xticks(x, ['none', 'fabricated\nerror', 'none', 'fabricated\nerror'])
ax.tick_params(axis='x', length=0)
ax.text(0.5, -30, 'General\nworking proof', ha='center', va='top', fontsize=6, transform=ax.transData)
ax.text(3.0, -30, 'Closed\ndecide instance', ha='center', va='top', fontsize=6, transform=ax.transData)
ax.set_ylim(0, 112); ax.set_yticks([0, 25, 50, 75, 100]); ax.set_ylabel('Correct responses (%)')
ax.set_title('Later batch, Opus + Haiku, 28 per cell', loc='left', pad=14)
ax.legend(loc='lower center', bbox_to_anchor=(0.5, 1.0), ncol=2, frameon=False, handlelength=1.0,
          borderaxespad=0.0, columnspacing=0.8, fontsize=5.5)
letter(ax, 'b')

# (c) grouped bars, provenance under fabricated success
ax = axes[2]
conds = [('RFL_FS', 'no block'), ('RFL_FS_prov_match', 'matching,\nrecent'), ('RFL_FS_prov_mismatch', 'mismatched,\nolder')]
x = [0, 1, 2]
for k_, (name, col) in enumerate([('Opus', BLUE), ('Haiku', RUST)]):
    for xi, (c, lab) in zip(x, conds):
        init, fin, n = panel_c[name][c]
        xx = xi + (-w / 2 if k_ == 0 else w / 2)
        ax.bar(xx, 100 * init / n, w, color=col, label=name if xi == 0 else None)
        ax.text(xx, 100 * init / n + 2, f'{init}', ha='center', fontsize=5.5, color=col)
ax.set_xticks(x, [c[1] for c in conds])
ax.set_xlabel('Provenance block shown')
ax.set_ylim(0, 112); ax.set_yticks([0, 25, 50, 75, 100]); ax.set_ylabel('Correct revisions (%)')
ax.set_title('Insufficient rfl, false success (13 per cell)', loc='left', pad=14, fontsize=6.2)
ax.legend(loc='lower center', bbox_to_anchor=(0.5, 1.0), ncol=2, frameon=False, handlelength=1.2,
          borderaxespad=0.0, columnspacing=1.2)
letter(ax, 'c')

output_dir = ROOT / 'figures'
output_dir.mkdir(parents=True, exist_ok=True)
fig.savefig(output_dir / 'fig1_final.png', dpi=300, facecolor='white')
plt.close(fig)
print('Figure regenerated from trial records.')
