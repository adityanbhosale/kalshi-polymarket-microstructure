# Discovery candidates — curated for manual review (D.1)

_Source: `data/processed/discovery_candidates.md`. 92 of 96 candidates retained (dropped 4 flagged `uncertain` / score < 0.5)._

## How to read this

- `match_type` is hand-assigned by reading each row's `kalshi_event` ↔ `polymarket_question` pair (not derived from `match_score`). Values:
  - `same_event` — both venues quote the same real-world outcome.
  - `same_race_diff_side` — same race/contest, different candidates.
  - `shared_entity_only` — share a candidate/team/asset name but ask different questions (e.g., primary vs general election with the same candidate).
  - `shared_domain_only` — share category words only (e.g., generic "Senate 2026" / "Republicans" overlap).
  - `shared_date_only` — coincide only on dates or generic terms (e.g., the USDBRL/XRP "Dec 31, 2026" pattern).
  - `ambiguous` — cannot determine from the title alone.
- `combined_vol_k` = `(kalshi_vol + poly_vol) / 1,000` (USD, thousands), as a quick liquidity proxy.

- Within each category, rows are sorted by `match_type` (`same_event` first) then by `combined_vol_k` descending.

## Sports

| kalshi_ticker | kalshi_event | polymarket_question | match_type | prob_bucket | combined_vol_k | days_to_resolution |
|---|---|---|---|---|---:|---:|
| `KXNBA-26-SAS` | Will the San Antonio win the 2026 Pro Basketball Finals? —… | Will the San Antonio Spurs win the 2026 NBA Finals? | `same_event` | `mid_low` | 64,237 | 763.5 |
| `KXNBA-26-OKC` | Will the Oklahoma City win the 2026 Pro Basketball Finals?… | Will the Oklahoma City Thunder win the 2026 NBA Finals? | `same_event` | `central` | 34,144 | 763.5 |
| `KXARODGRETIRE-26` | Will Aaron Rodgers announce their retirement in 2026? — Bef… | Will Aaron Rodgers retire before next season? | `same_event` | `tail_low` | 307 | 99.5 |
| `KXKELCERETIRE-26` | Will Travis Kelce announce his retirement before the 2026-2… | Will Travis Kelce retire before next season? | `same_event` | `tail_low` | 139 | 109.1 |
| `KXNBA-26-NYK` | Will the New York win the 2026 Pro Basketball Finals? — New… | Will the Republicans win the New York governor race in 2026? | `shared_domain_only` | `central` | 29,665 | 763.5 |
| `KXLBJRETIRE-26` | Will LeBron James announce his retirement in 2026? — Before… | Will there be another US government shutdown by January 31… | `shared_domain_only` | `tail_low` | 617 | 156.5 |

_4 same_event, 2 shared_domain_only._

## Politics

| kalshi_ticker | kalshi_event | polymarket_question | match_type | prob_bucket | combined_vol_k | days_to_resolution |
|---|---|---|---|---|---:|---:|
| `KXMAYORLA-26-SPRA` | Who will win Los Angeles Mayoral Election? — Spencer Pratt | Will Spencer Pratt win the 2026 Los Angeles mayoral electio… | `same_event` | `mid_low` | 20,851 | 370.5 |
| `KXPERUPRES-26-RPAL` | Will Roberto Sánchez Palomino win the next Peruvian preside… | Will Roberto Sánchez Palomino win the 2026 Peruvian preside… | `same_event` | `mid_low` | 14,009 | 319.5 |
| `KXPERUPRES-26-KFUJ` | Who will win the next Peruvian presidential election? — Kei… | Will Keiko Fujimori win the 2026 Peruvian presidential elec… | `same_event` | `mid_high` | 7,674 | 319.5 |
| `KXMAYORLA-26-KBAS` | Who will win Los Angeles Mayoral Election? — Karen Bass | Will Karen Bass win the 2026 Los Angeles mayoral election? | `same_event` | `central` | 2,407 | 370.5 |
| `KXSEOULMAYOR-26JUN03-OSEH` | Will Oh Se-hoon win the 2026 Seoul mayoral election? — Oh S… | Will Oh Se-hoon win the 2026 Seoul Mayoral Election | `same_event` | `mid_low` | 2,234 | 371.5 |
| `KXMAYORLA-26-NRAM` | Who will win Los Angeles Mayoral Election? — Nithya Raman | Will Nithya Raman win the 2026 Los Angeles mayoral election? | `same_event` | `tail_low` | 2,136 | 370.5 |
| `KXCOLOMBIAPRES-26-AESP` | Will Abelardo de la Espriella win the next Colombian presid… | Will Abelardo de la Espriella  win the 2026 Colombian presi… | `same_event` | `central` | 2,081 | 368.5 |
| `KXCOLOMBIAPRES-26-PVAL` | Will Paloma Valencia win the next Colombian presidential el… | Will Paloma Valencia win the 2026 Colombian presidential el… | `same_event` | `tail_low` | 1,926 | 368.5 |
| `KXCOLOMBIAPRESR1-26MAY31-ICAS` | Will Iván Cepeda Castro win the first round of the 2026 Col… | Will Iván Cepeda Castro win the 1st round of the 2026 Colom… | `same_event` | `central` | 1,111 | 368.5 |
| `KXMAYORLA-26-RHUA` | Who will win Los Angeles Mayoral Election? — Rae Huang | Will Rae Huang win the 2026 Los Angeles mayoral election? | `same_event` | `tail_low` | 724 | 370.5 |
| `KXMAYORLA-26-AMIL` | Who will win Los Angeles Mayoral Election? — Adam Miller | Will Adam Miller win the 2026 Los Angeles mayoral election? | `same_event` | `tail_low` | 707 | 370.5 |
| `KXMAYORLA-26-RCAR` | Who will win Los Angeles Mayoral Election? — Rick Caruso | Will Rick Caruso win the 2026 Los Angeles mayoral election? | `same_event` | `tail_low` | 685 | 370.5 |
| `KXAKSENATE-26NOV03-MPEL` | Will Mary Peltola win the 2026 Alaska Senate race? — Mary P… | Will Mary Peltola win the Alaska Senate race in 2026? | `same_event` | `central` | 197 | 524.6 |
| `KXGOVCAPRIMARY-26-TSTE` | Who will win California's top-two primary for governor? — T… | Will Tom Steyer win the California Governor Election in 202… | `shared_entity_only` | `central` | 3,633 | 159.6 |
| `KXLAMAYOR1R-26-SPRA` | Who will win the first round of the Los Angeles mayoral ele… | Will Spencer Pratt win the 2026 Los Angeles mayoral electio… | `shared_entity_only` | `mid_low` | 1,952 | 370.5 |
| `KXCOLOMBIAPRESR1-26MAY31-AESP` | Will Abelardo de la Espriella win the first round of the 20… | Will Abelardo de la Espriella  win the 2026 Colombian presi… | `shared_entity_only` | `central` | 1,898 | 368.5 |
| `KXCOLOMBIAPRESR1-26MAY31-PVAL` | Will Paloma Valencia win the first round of the 2026 Colomb… | Will Paloma Valencia win the 2026 Colombian presidential el… | `shared_entity_only` | `tail_low` | 1,825 | 368.5 |
| `KXGOVCAPRIMARY-26-CBIA` | Who will win California's top-two primary for governor? — C… | Will Chad Bianco win the California Governor Election in 20… | `shared_entity_only` | `tail_low` | 1,747 | 159.6 |
| `KXGOVCAPRIMARY-26-SHIL` | Who will win California's top-two primary for governor? — S… | Will Steve Hilton win the California Governor Election in 2… | `shared_entity_only` | `mid_high` | 1,606 | 159.6 |
| `KXGOVCAPRIMARY-26-KPOR` | Who will win California's top-two primary for governor? — K… | Will Katie Porter win the California Governor Election in 2… | `shared_entity_only` | `tail_low` | 1,301 | 159.6 |
| `KXGOVCAPRIMARY-26-XBEC` | Who will win California's top-two primary for governor? — X… | Will Xavier Becerra win the California Governor Election in… | `shared_entity_only` | `mid_high` | 1,187 | 159.6 |
| `KXCOLOMBIAPRES-26-ICAS` | Will Iván Cepeda Castro win the next Colombian presidential… | Will Iván Cepeda Castro win the 1st round of the 2026 Colom… | `shared_entity_only` | `central` | 1,092 | 368.5 |
| `KXGOVCAPRIMARY-26-ESWA` | Who will win California's top-two primary for governor? — E… | Will Eric Swalwell win the California Governor Election in… | `shared_entity_only` | `tail_low` | 1,058 | 159.6 |
| `KXLAMAYOR1R-26-NRAM` | Who will win the first round of the Los Angeles mayoral ele… | Will Nithya Raman win the 2026 Los Angeles mayoral election? | `shared_entity_only` | `tail_low` | 213 | 370.5 |
| `KXLAMAYOR1R-26-KBAS` | Who will win the first round of the Los Angeles mayoral ele… | Will Karen Bass win the 2026 Los Angeles mayoral election? | `shared_entity_only` | `mid_high` | 205 | 370.5 |
| `KXCA11PRIMARY-26-CCHA` | Who will win the 2026 CA-11 primary? — Connie Chan | Will Chad Bianco win the California Governor Election in 20… | `shared_domain_only` | `central` | 1,435 | 159.6 |
| `KXCA11PRIMARY-26-SWIE` | Who will win the 2026 CA-11 primary? — Scott Wiener | Will Kamala Harris win the California Governor Election in… | `shared_domain_only` | `tail_high` | 1,160 | 159.6 |
| `KXISRAELKNESSET-26-BEN` | Will Bennett 2026 win the next Israeli legislative election… | Will Asia win the 2026 FIFA World Cup? | `shared_domain_only` | `tail_low` | 389 | 517.5 |
| `KXIRANDEMOCRACY-27MAR01-T6` | Will Iran's score in the Economist Intelligence Unit's Demo… | Will GTA 6 cost $100+? | `shared_domain_only` | `tail_low` | 372 | 277.6 |
| `KXHOUSEPOPVOTEMARGIN-27NOV03-B50` | Will Republicans win the 2026 U.S. House of Representatives… | Will the Republicans win the Iowa Senate race in 2026? | `shared_domain_only` | `mid_low` | 250 | 524.5 |
| `KXAKSENATE-26NOV03-DSUL` | Will Dan Sullivan win the 2026 Alaska Senate race? — Dan Su… | Will the Democrats win the Maine Senate race in 2026? | `shared_domain_only` | `central` | 228 | 524.6 |
| `KXSENATEDEMLEAD-28JAN01-CMUR` | Will Chris Murphy win the next Senate Democratic Leader ele… | Will the Democrats win the Maine Senate race in 2026? | `shared_domain_only` | `tail_low` | 221 | 948.6 |
| `KXGOVCAPRIMARYPARTY-26-2R` | Who will advance from California's top-two primary for gove… | Will the Republicans win the Minnesota governor race in 202… | `shared_domain_only` | `tail_low` | 178 | 370.5 |
| `KXCA11PRIMARY-26-SCHA` | Who will win the 2026 CA-11 primary? — Saikat Chakrabarti | Will Dan Sullivan win the Alaska Senate race in 2026? | `shared_domain_only` | `central` | 155 | 159.6 |
| `KXSEOULMAYOR-26JUN03-CWON` | Will Chong Won-o win the 2026 Seoul mayoral election? — Cho… | Will the Republicans win the Ohio governor race in 2026? | `shared_domain_only` | `mid_high` | 132 | 371.5 |
| `KXGOVCAPRIMARYPARTY-26-2D` | Who will advance from California's top-two primary for gove… | Will the Democrats win the Rhode Island governor race in 20… | `shared_domain_only` | `mid_low` | 112 | 370.5 |
| `KXMAKERFIELDBY-27JAN01-RES` | Will Restore Britain win the 2026 Makerfield by-election? —… | Will Nicolás Maduro be sentenced to at least 60 years in pr… | `shared_domain_only` | `tail_low` | 104 | 583.6 |
| `KXCA14SWINNER-26-RSIN` | Who will win the 2026 CA-14 special election? — Rakhi Isran… | Will the Republican Party hold exactly 48 Senate seats afte… | `shared_domain_only` | `tail_low` | 101 | 524.6 |
| `KXMAKERFIELDBY-27JAN01-LAB` | Will Labour win the 2026 Makerfield by-election? — Labour | Will Nicolás Maduro be sentenced to less than 20 years in p… | `shared_domain_only` | `mid_high` | 100 | 583.6 |
| `KXINSOSNOMR-26-DMOR` | Who will win 2026 Indiana Secretary of State Republican pri… | Will the Republicans win the Montana Senate race in 2026? | `shared_domain_only` | `tail_low` | 77 | 342.5 |
| `KXCA14SWINNER-26-AWAH` | Who will win the 2026 CA-14 special election? — Aisha Wahab | Will the Republicans win the North Carolina Senate race in… | `shared_domain_only` | `tail_high` | 69 | 524.6 |
| `KXHOUSEPOPVOTEMARGIN-27NOV03-B1` | Will the Democratic margin of victory in the 2026 U.S. Hous… | Will the Democratic Progressive Party (DPP) win the most he… | `shared_domain_only` | `tail_low` | 63 | 524.5 |
| `KXBERNIEENDORSE-26NOV03-JTAL` | Will Bernie Sanders endorse James Talarico in the 2026 Unit… | Will Ann Diener win the Alaska Senate race in 2026? | `shared_domain_only` | `mid_high` | 62 | 159.6 |

_13 same_event, 12 shared_entity_only, 18 shared_domain_only._

## Macro

| kalshi_ticker | kalshi_event | polymarket_question | match_type | prob_bucket | combined_vol_k | days_to_resolution |
|---|---|---|---|---|---:|---:|
| `KXFM30YMTG-26DEC31-T5.75` | Will any 2026 Freddie Mac Primary Mortgage Market Survey (P… | Freddie Mac IPO before 2027? | `shared_entity_only` | `tail_low` | 284 | 217.6 |
| `KXECONSTATCPICORE-26MAY-T-0.1` | CPI core month-over-month in May 2026? — Exactly -0.1% | Will Chong Won-oh win the 2026 Seoul Mayoral Election | `shared_domain_only` | `tail_low` | 1,679 | 13.5 |
| `KXECONSTATCPICORE-26MAY-T-0.2` | CPI core month-over-month in May 2026? — Exactly -0.2% | Will Chong Won-oh win the 2026 Seoul Mayoral Election | `shared_domain_only` | `tail_low` | 1,436 | 13.5 |
| `KXECONSTATCPICORE-26MAY-T0.3` | CPI core month-over-month in May 2026? — Exactly 0.3% | Will Chong Won-oh win the 2026 Seoul Mayoral Election | `shared_domain_only` | `mid_low` | 1,424 | 13.5 |
| `KXECONSTATCPICORE-26MAY-T0.5` | CPI core month-over-month in May 2026? — Exactly 0.5% | Will Chong Won-oh win the 2026 Seoul Mayoral Election | `shared_domain_only` | `tail_low` | 1,416 | 13.5 |
| `KXECONSTATCPICORE-26MAY-T0.0` | CPI core month-over-month in May 2026? — Exactly 0.0% | Will Chong Won-oh win the 2026 Seoul Mayoral Election | `shared_domain_only` | `tail_low` | 1,413 | 13.5 |
| `KXTARIFFCHECKS-26-27` | Will it be reported that at least one million Americans hav… | Will Monero hit $1000 in 2026? | `shared_domain_only` | `mid_low` | 965 | 218.1 |
| `KXECONSTATCORECPIYOY-26JUN-T2.3` | CPI core year-over-year in Jun 2026? — Exactly 2.3% | Will Clara Tauson be the 2026 Women’s Wimbledon Winner? | `shared_domain_only` | `tail_low` | 745 | 47.5 |
| `KXECONSTATCPI-26JUN-T-0.2` | CPI month-over-month in Jun 2026? — Exactly -0.2% | Will Clara Tauson be the 2026 Women’s Wimbledon Winner? | `shared_domain_only` | `tail_low` | 710 | 47.5 |
| `KXTARIFFCHECKS-26-AUG` | Will it be reported that at least one million Americans hav… | Will Chellie Pingree be the Democratic nominee for Senate i… | `shared_domain_only` | `tail_low` | 696 | 65.1 |
| `KXECONSTATCPI-26JUN-T-0.1` | CPI month-over-month in Jun 2026? — Exactly -0.1% | Will Clara Tauson be the 2026 Women’s Wimbledon Winner? | `shared_domain_only` | `tail_low` | 626 | 47.5 |
| `KXTARIFFCHECKS-26-JUL` | Will it be reported that at least one million Americans hav… | Will Z.ai have the top AI model at the end of June 2026? | `shared_domain_only` | `tail_low` | 593 | 34.1 |
| `KXECONSTATCPI-26JUN-T0.0` | CPI month-over-month in Jun 2026? — Exactly 0.0% | Will Clara Tauson be the 2026 Women’s Wimbledon Winner? | `shared_domain_only` | `mid_low` | 589 | 47.5 |
| `KXECONSTATCORECPIYOY-26JUN-T2.2` | CPI core year-over-year in Jun 2026? — Exactly 2.2% | Will Clara Tauson be the 2026 Women’s Wimbledon Winner? | `shared_domain_only` | `tail_low` | 476 | 47.5 |
| `KXECONSTATCORECPIYOY-26JUN-T3.5` | CPI core year-over-year in Jun 2026? — Exactly 3.5% | Will Paula Badosa be the 2026 Women’s Wimbledon Winner? | `shared_domain_only` | `tail_low` | 319 | 47.5 |
| `KXECONSTATCORECPIYOY-26JUL-T3.7` | CPI core year-over-year in Jul 2026? — Exactly 3.7% | Will Charity Clark win the 2026 Vermont Governor Democratic… | `shared_domain_only` | `tail_low` | 315 | 76.5 |
| `KXECONSTATCORECPIYOY-26JUL-T2.5` | CPI core year-over-year in Jul 2026? — Exactly 2.5% | Will Charity Clark win the 2026 Vermont Governor Democratic… | `shared_domain_only` | `tail_low` | 254 | 76.5 |
| `KXCHAICUTS-26JUN04-T1` | Will “Artificial Intelligence” be the #1 reason for job cut… | Will Park Chan-dae win the 2026 Incheon mayoral election? | `shared_domain_only` | `mid_high` | 198 | 7.3 |
| `KXDEFGDP-26OCT20-T5` | Will U.S. federal deficit-to-GDP for FY2026 be below 5%? —… | Will LeBron James retire before next NBA season? | `shared_domain_only` | `tail_low` | 195 | 145.5 |
| `KXECONSTATCORECPIYOY-26JUN-T3.6` | CPI core year-over-year in Jun 2026? — Exactly 3.6% | Will Paula Badosa be the 2026 Women’s Wimbledon Winner? | `shared_domain_only` | `tail_low` | 183 | 47.5 |
| `KXTARIFFCHECKS-26-JUN` | Will it be reported that at least one million Americans hav… | Will one Democratic Party candidate and one Republican Part… | `shared_domain_only` | `tail_low` | 140 | 4.1 |
| `KXCOST-26MAYCARDS-150000000.0` | Will Costco Wholesale Corporation report above 150 million… | Will Keaton Verhoeff be drafted 1st overall in the 2026 NHL… | `shared_domain_only` | `tail_low` | 107 | 30.8 |
| `KXCOREUND-26DEC10-T2.2` | Will year-over-year Core CPI inflation for 2026 fall below… | Will the upper bound of the target federal funds rate be 2.… | `shared_domain_only` | `mid_low` | 104 | 196.5 |
| `KXECONSTATCORECPIYOY-26JUL-T2.2` | CPI core year-over-year in Jul 2026? — Exactly 2.2% | Will Charity Clark win the 2026 Vermont Governor Democratic… | `shared_domain_only` | `tail_low` | 95 | 76.5 |
| `KXTSLA-26JULPROD-440000.0` | Will Tesla Inc. report above 440000 total production in Q2… | Will Treg Taylor advance from the 2026 Alaska Governor prim… | `shared_domain_only` | `central` | 95 | 85.8 |
| `KXECONSTATCORECPIYOY-26JUL-T2.3` | CPI core year-over-year in Jul 2026? — Exactly 2.3% | Will Charity Clark win the 2026 Vermont Governor Democratic… | `shared_domain_only` | `tail_low` | 91 | 76.5 |
| `KXNFPROD-27MAR04-T3` | Will U.S. nonfarm productivity YoY in any quarter for 2026… | Will the Democrats win the New York governor race in 2026? | `shared_domain_only` | `central` | 88 | 280.5 |
| `KXTSLA-26JULPROD-420000.0` | Will Tesla Inc. report above 420000 total production in Q2… | Will Treg Taylor advance from the 2026 Alaska Governor prim… | `shared_domain_only` | `central` | 88 | 85.8 |
| `KXTSLA-26JULDELIV-450000.0` | Will Tesla Inc. report above 450000 total deliveries in Q2… | Will Treg Taylor advance from the 2026 Alaska Governor prim… | `shared_domain_only` | `mid_low` | 83 | 85.8 |
| `KXCOST-26MAYCARDS-147000000.0` | Will Costco Wholesale Corporation report above 147 million… | Will Keaton Verhoeff be drafted 1st overall in the 2026 NHL… | `shared_domain_only` | `tail_high` | 69 | 30.8 |
| `KXCOST-26MAYCARDS-149000000.0` | Will Costco Wholesale Corporation report above 149 million… | Will Keaton Verhoeff be drafted 1st overall in the 2026 NHL… | `shared_domain_only` | `central` | 62 | 30.8 |
| `KXUSDBRLMAX-26DEC31-T6.9999` | Will the maximum USD/BRL exchange rate reach 6.9999 by Dec… | Will XRP reach $5.00 by December 31, 2026? | `shared_date_only` | `tail_low` | 310 | 217.6 |
| `KXUSDBRLMAX-26DEC31-T6.4999` | Will the maximum USD/BRL exchange rate reach 6.4999 by Dec… | Will XRP reach $5.00 by December 31, 2026? | `shared_date_only` | `tail_low` | 168 | 217.6 |
| `KXUSDBRLMAX-26DEC31-T6.7499` | Will the maximum USD/BRL exchange rate reach 6.7499 by Dec… | Will XRP reach $5.00 by December 31, 2026? | `shared_date_only` | `tail_low` | 114 | 217.6 |
| `KXUSDBRLMAX-26DEC31-T7.2499` | Will the maximum USD/BRL exchange rate reach 7.2499 by Dec… | Will XRP reach $5.00 by December 31, 2026? | `shared_date_only` | `tail_low` | 99 | 217.6 |
| `KXUSDBRLMAX-26DEC31-T5.9999` | Will the maximum USD/BRL exchange rate reach 5.9999 by Dec… | Will XRP reach $5.00 by December 31, 2026? | `shared_date_only` | `central` | 73 | 217.6 |

_1 shared_entity_only, 30 shared_domain_only, 5 shared_date_only._

## Crypto

| kalshi_ticker | kalshi_event | polymarket_question | match_type | prob_bucket | combined_vol_k | days_to_resolution |
|---|---|---|---|---|---:|---:|
| _no candidates_ | | | | | | |

_(empty)_

## Cultural / Tail-event

| kalshi_ticker | kalshi_event | polymarket_question | match_type | prob_bucket | combined_vol_k | days_to_resolution |
|---|---|---|---|---|---:|---:|
| `KXTAKEOVERACQWB-27JUN30-PSKY` | Will Paramount's takeover of Warner Brothers succeed Before… | Will Paramount close Warner Bros acquisition? | `same_event` | `mid_high` | 1,911 | 399.1 |
| `KXTAKEOVERACQWB-27JUN30-NFLX` | Will Netflix's takeover of Warner Brothers succeed Before J… | Will Netflix close Warner Bros acquisition? | `same_event` | `tail_low` | 1,519 | 399.1 |
| `KXTRUMPATTEND` | Will Donald J. Trump attend The 2026 FIFA World Cup Final?… | Will USA win the 2026 FIFA World Cup? | `shared_domain_only` | `mid_high` | 39,560 | 53.5 |
| `KXTRUMPNBAFINALS-26JUN-DJT` | Will Donald Trump attend any 2026 Pro Basketball finals gam… | Will Roy Barreras win the 2026 Colombian presidential elect… | `shared_domain_only` | `mid_high` | 1,297 | 23.5 |
| `KXTAKEOVERACQWB-27JUN30-NONE` | Will None's takeover of Warner Brothers succeed Before July… | Ramp IPO before 2027? | `shared_domain_only` | `mid_low` | 836 | 399.1 |
| `KXTRUMPUFC-26JUL-DJT` | Will Donald Trump attend UFC 329? — Yes | Will Sonay Kartal be the 2026 Women’s Wimbledon Winner? | `shared_domain_only` | `mid_low` | 216 | 45.5 |
| `KXTRUMPBALLROOM-28JAN01` | Will it be reported that the White House State Ballroom is… | Will Anthropic’s market cap be between $100B and $200B at m… | `shared_domain_only` | `tail_low` | 85 | 583.1 |

_2 same_event, 5 shared_domain_only._

## Overall match_type distribution

- `same_event`: 19
- `shared_entity_only`: 13
- `shared_domain_only`: 55
- `shared_date_only`: 5
