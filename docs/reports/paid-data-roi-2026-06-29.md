# Paid-Data ROI — quelle data payante = meilleur ROI (focus options/inefficiences) — 2026-06-29

> Recherche web (5 agents) pondérée vers l'ambition de l'opérateur : un **scanner d'inefficiences options** ("bots qui campent"). ROI = impact-nouvel-edge par $, adapté à notre thèse (solo · maker · non-latence · niche/desk-invisible · le Gate). Findings-only.

## 1. BLUF — **dépense $0 d'abord**

Le meilleur ROI **n'est pas un abonnement** : c'est de **cloner le logger HL #479 en un logger Deribit** (API publique **gratuite, non-authentifiée**, rate-limit IP seulement) qui hoarde le **book L2 + mark-IV + greeks + DVOL** de BTC/ETH + 2-3 alts. C'est **la seule source options qui colle à notre thèse** (solo, maker, non-latence, niche), et elle est **additive** au lead HL ($0) — Deribit options ≠ HL (options natives HL pas avant Q3 2026).

**Le mur n'est PAS l'accès data — c'est la FILLABILITÉ.** Recherche académique + vendeurs convergent : la plupart des "inefficiences" options crypto (violations de parité put-call, kinks de surface) **s'évaporent dès qu'on traverse le bid-ask large hors-ATM**. **Aucun feed payant ne corrige ça** — seul **logger ton propre top-of-book simultané** à côté de l'edge apparent le prouve. Donc la validation la moins chère est la même partout : **$0**.

**Le 1er dollar payant** (seulement APRÈS qu'un signal Deribit gratuit survive au Gate, net de frais + fill maker réaliste) = **Velo Data ($199/mo)** (cross-venue 1-min propre, évite la "stitching tax") ou **Laevitas x402 (centimes/requête en USDC)** pour le block-flow. **Tout ce qui est ≥4 chiffres** (Amberdata, Kaiko, Allium, RavenPack, X Enterprise) = derrière une preuve-Gate, ou **à éviter**.

## 2. Table classée par ROI (notre niche maker/non-latence)

| # | Source | Edge débloqué (pour NOUS) | $/mo | Impact | ROI | Crowding | Validation gratuite avant d'acheter |
|---|--------|---------------------------|------|:---:|:---:|---|---|
| 1 | **Deribit API publique** | vol-surface / calendar / term-structure / no-arb statique + IV-vs-RV sur strikes alt/far-OTM/far-dated low-OI. **Le substrat du scanner.** | **$0** | 8-9 | **10** | ATM BTC/ETH arb'd ; long-tail sous-capacité = notre lane | déjà gratuit : logger book+IV → R2 (clone #479), 2-4 sem, puis Gate les buckets long-tail net de fee+fill |
| 2 | **Coinalyze API** | OI/funding/**predicted**-funding/liq/basis cross-venue agrégés (les primitives que CoinGlass facture $299) **gratuit**. Edge = *divergence*, pas niveaux | **$0** | 6 | **9** | funding/OI = les + arbés ; edge seulement dans la divergence + venues long-tail | clé gratuite : backfill + Gate funding-term-structure + OI-divergence |
| 3 | **Dune Analytics** | feature on-chain **propriétaire** (cohort/net-flow) que personne ne calcule | **$0**→$75 | 5 | **7** | ta requête privée n'est PAS crowded | tier gratuit : net-flow labellisé sur ~30 mid-caps, freeze as-of, Gate |
| 4 | **PredictionData.dev** | books L2 tick + fills onchain Polymarket/Kalshi → débloque le model-vs-market sur marchés niche | $450→$1250 | 7 | **7** | arb cross-venue vig-bound ; model-vs-market lent sur niche survit | CLOB/Gamma + Kalshi GRATUIT : refais le join résolution + dispute-flag toi-même |
| 5 | **Velo Data** | cross-venue 1-min propre (futures+options+funding+OI) — tue la stitching tax | $199 | 7 | **7** | mid : outil quant-retail | valider gratuit (Deribit+Coinalyze) D'ABORD ; 1 mois quand le goulot = propreté pas signal |
| 6 | **Laevitas (x402)** | block-trades + flow stratégies-options + surface, **pay-per-request en USDC** = la sonde payante la moins chère | centimes/call | 7 | **5** | block-flow long-tail genuinely sous-observé | micro-billing x402 : quelques semaines de block-flow, teste s'il lead le prix/vol |
| 7 | **Amberdata Derivatives** | **historique tick Deribit depuis 2021** + surface SVI — transforme le hoard forward-only en dataset multi-années backtestable. **Plus gros IMPACT options.** | ~$1-3k | 7-8 | **4-8** | couche analytics = desk-default ; valeur = l'historique RAW | **ne PAS acheter à l'aveugle** : trial gratuit, achète 1 mois S3 SEULEMENT quand un bucket survit + tu as besoin d'années pour sizer |
| 8-10 | Santiment $49 (quality-screen, pas timing) · LunarCrush (forward-capture only, histoire PIT-malhonnête) · Token Terminal/Artemis gratuits (facteur value lent) | — | $0-249 | 4-5 | **4-5** | sentiment retail-saturé | tester 1 mois, kill si pas de pouls |
| 11-15 | **À ÉVITER / faible ROI** : Polygon/ORATS/CBOE equity-options (le dataset **le + arbé du monde**, classes rapides gone-in-ms) · Nansen/Arkham ("Smart Money" = front-run ~20min par copy-bots) · CoinGlass (heatmap MODELED, peinte, edge négatif sur la lecture évidente) · Unusual Whales (retail maximalement crowded, réactif) · Glassnode/RavenPack/Kaiko/X-Enterprise (4-5 chiffres) | — | $29-42k | 4-6 | **2-4** | desk-default / PIT-malhonnête / trop cher | reconstruire gratuit d'abord ; acheter seulement si le gratuit survit |

## 3. Verdict scanner d'inefficiences options (ta priorité)

- ✅ **Faisable, et le substrat est GRATUIT (Deribit).** Les classes réalistes pour un **maker non-latence** : vol-surface / calendar-spread / term-structure / IV-vs-RV (vol-risk-premium) sur **strikes long-tail low-OI** (sous-capacité = notre lane).
- ❌ **Pas les classes liquides/rapides** (ATM BTC/ETH, parité put-call textbook) = arbées en ms par plus rapides.
- 🔑 **Le test décisif = logger ton PROPRE top-of-book simultané** à côté de l'edge apparent (sinon = mirage de quote périmé). Chaque classe = une hypothèse → **Gate BRUT** net de frais Deribit + fill maker réaliste.

## 4. Plan de dépense étagé

1. **$0** : logger Deribit (clone #479) → hoard 2-4 semaines → Gate les buckets long-tail. **+ Coinalyze gratuit** (divergence funding/OI).
2. **$199 Velo** *seulement* quand le goulot devient propreté/couverture (pas existence du signal).
3. **Laevitas x402 (centimes)** pour sonder le block-flow sans abonnement.
4. **Amberdata 1-mois** *seulement* quand un bucket survit + besoin d'années d'historique pour sizer.
5. **Jamais** : Nansen/CoinGlass-heatmap/Unusual-Whales/equity-options-rapides à l'aveugle.

**Bottom line : la prochaine action la moins chère et la plus haut-ROI pour l'ambition options = un logger Deribit gratuit (même pattern que #479 HL). Zéro dollar tant que le Gate n'a pas validé un bucket.**
