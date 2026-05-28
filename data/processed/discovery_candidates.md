# Discovery candidates — D.1

_Generated 2026-05-28 01:32:17Z_  _Source: scripts/discover_markets.py_

## Constants used

- `MIN_KALSHI_VOLUME_USD`     = $25,000
- `MIN_POLYMARKET_VOLUME_USD` = $25,000
- `MIN_COMBINED_OI_USD`       = $50,000
- `MIN_DAYS_TO_RESOLUTION`    = 2 days
- Probability buckets: `tail_low`=0.00-0.10, `mid_low`=0.10-0.30, `central`=0.30-0.70, `mid_high`=0.70-0.90, `tail_high`=0.90-1.00

## Pipeline counts

- Kalshi series fetched: **10441**
- Kalshi series after parlay filter: **501**
- Kalshi markets surviving volume + days-to-resolution filters: **96**
- Polymarket active markets in matching pool: **2373**
- Candidate rows below: **96** (high-confidence ≥0.5: **92**)

## Candidates (sorted by match score)

| kalshi_ticker | kalshi_event | polymarket_question | kalshi_vol | poly_vol | prob_bucket | days_to_resolution | match_score | notes |
|---|---|---|---|---|---|---|---|---|
| KXKELCERETIRE-26 | Will Travis Kelce announce his retirement before the 2026-27 regular… | Will Travis Kelce retire before next season? | $97,758 | $40,947 | tail_low | 109.1 | 0.845 |  |
| KXUSDBRLMAX-26DEC31-T7.2499 | Will the maximum USD/BRL exchange rate reach 7.2499 by Dec 31, 2026?… | Will XRP reach $5.00 by December 31, 2026? | $56,738 | $42,550 | tail_low | 217.6 | 0.790 |  |
| KXUSDBRLMAX-26DEC31-T6.9999 | Will the maximum USD/BRL exchange rate reach 6.9999 by Dec 31, 2026?… | Will XRP reach $5.00 by December 31, 2026? | $267,215 | $42,550 | tail_low | 217.6 | 0.790 |  |
| KXUSDBRLMAX-26DEC31-T6.7499 | Will the maximum USD/BRL exchange rate reach 6.7499 by Dec 31, 2026?… | Will XRP reach $5.00 by December 31, 2026? | $71,251 | $42,550 | tail_low | 217.6 | 0.790 |  |
| KXUSDBRLMAX-26DEC31-T6.4999 | Will the maximum USD/BRL exchange rate reach 6.4999 by Dec 31, 2026?… | Will XRP reach $5.00 by December 31, 2026? | $125,376 | $42,550 | tail_low | 217.6 | 0.790 |  |
| KXUSDBRLMAX-26DEC31-T5.9999 | Will the maximum USD/BRL exchange rate reach 5.9999 by Dec 31, 2026?… | Will XRP reach $5.00 by December 31, 2026? | $30,008 | $42,550 | central | 217.6 | 0.790 |  |
| KXTRUMPATTEND | Will Donald J. Trump attend The 2026 FIFA World Cup Final? — Yes | Will USA win the 2026 FIFA World Cup? | $54,876 | $39,504,917 | mid_high | 53.5 | 0.785 |  |
| KXGOVCAPRIMARY-26-XBEC | Who will win California's top-two primary for governor? — Xavier Bece… | Will Xavier Becerra win the California Governor Election in 2026? | $242,507 | $944,937 | mid_high | 159.6 | 0.743 |  |
| KXBERNIEENDORSE-26NOV03-JTAL | Will Bernie Sanders endorse James Talarico in the 2026 United States… | Will Ann Diener win the Alaska Senate race in 2026? | $27,350 | $34,206 | mid_high | 159.6 | 0.741 |  |
| KXGOVCAPRIMARY-26-ESWA | Who will win California's top-two primary for governor? — Eric Swalwe… | Will Eric Swalwell win the California Governor Election in 2026? | $114,410 | $943,795 | tail_low | 159.6 | 0.739 |  |
| KXGOVCAPRIMARY-26-SHIL | Who will win California's top-two primary for governor? — Steve Hilton | Will Steve Hilton win the California Governor Election in 2026? | $194,853 | $1,411,555 | mid_high | 159.6 | 0.735 |  |
| KXGOVCAPRIMARY-26-KPOR | Who will win California's top-two primary for governor? — Katie Porter | Will Katie Porter win the California Governor Election in 2026? | $104,989 | $1,195,883 | tail_low | 159.6 | 0.735 |  |
| KXGOVCAPRIMARY-26-CBIA | Who will win California's top-two primary for governor? — Chad Bianco | Will Chad Bianco win the California Governor Election in 2026? | $358,352 | $1,388,587 | tail_low | 159.6 | 0.731 |  |
| KXGOVCAPRIMARY-26-TSTE | Who will win California's top-two primary for governor? — Tom Steyer | Will Tom Steyer win the California Governor Election in 2026? | $243,248 | $3,389,850 | central | 159.6 | 0.727 |  |
| KXCOLOMBIAPRESR1-26MAY31-PVAL | Will Paloma Valencia win the first round of the 2026 Colombian presid… | Will Paloma Valencia win the 2026 Colombian presidential election? | $48,424 | $1,776,464 | tail_low | 368.5 | 0.700 |  |
| KXCOLOMBIAPRESR1-26MAY31-AESP | Will Abelardo de la Espriella win the first round of the 2026 Colombi… | Will Abelardo de la Espriella  win the 2026 Colombian presidential el… | $170,027 | $1,727,779 | central | 368.5 | 0.700 |  |
| KXFM30YMTG-26DEC31-T5.75 | Will any 2026 Freddie Mac Primary Mortgage Market Survey (PMMS) repor… | Freddie Mac IPO before 2027? | $38,541 | $245,184 | tail_low | 217.6 | 0.687 |  |
| KXCA11PRIMARY-26-SWIE | Who will win the 2026 CA-11 primary? — Scott Wiener | Will Kamala Harris win the California Governor Election in 2026? | $40,429 | $1,119,819 | tail_high | 159.6 | 0.683 |  |
| KXCOLOMBIAPRESR1-26MAY31-ICAS | Will Iván Cepeda Castro win the first round of the 2026 Colombian pre… | Will Iván Cepeda Castro win the 1st round of the 2026 Colombian presi… | $220,992 | $890,299 | central | 368.5 | 0.682 |  |
| KXCA11PRIMARY-26-CCHA | Who will win the 2026 CA-11 primary? — Connie Chan | Will Chad Bianco win the California Governor Election in 2026? | $45,962 | $1,388,587 | central | 159.6 | 0.681 |  |
| KXAKSENATE-26NOV03-DSUL | Will Dan Sullivan win the 2026 Alaska Senate race? — Dan Sullivan | Will the Democrats win the Maine Senate race in 2026? | $33,900 | $194,421 | central | 524.6 | 0.677 |  |
| KXCOLOMBIAPRES-26-AESP | Will Abelardo de la Espriella win the next Colombian presidential ele… | Will Abelardo de la Espriella  win the 2026 Colombian presidential el… | $352,970 | $1,727,779 | central | 368.5 | 0.676 |  |
| KXPERUPRES-26-RPAL | Will Roberto Sánchez Palomino win the next Peruvian presidential elec… | Will Roberto Sánchez Palomino win the 2026 Peruvian presidential elec… | $655,884 | $13,353,344 | mid_low | 319.5 | 0.676 |  |
| KXCA11PRIMARY-26-SCHA | Who will win the 2026 CA-11 primary? — Saikat Chakrabarti | Will Dan Sullivan win the Alaska Senate race in 2026? | $63,130 | $91,592 | central | 159.6 | 0.675 |  |
| KXCOLOMBIAPRES-26-PVAL | Will Paloma Valencia win the next Colombian presidential election? —… | Will Paloma Valencia win the 2026 Colombian presidential election? | $149,981 | $1,776,464 | tail_low | 368.5 | 0.672 |  |
| KXCOLOMBIAPRES-26-ICAS | Will Iván Cepeda Castro win the next Colombian presidential election?… | Will Iván Cepeda Castro win the 1st round of the 2026 Colombian presi… | $201,972 | $890,299 | central | 368.5 | 0.664 |  |
| KXAKSENATE-26NOV03-MPEL | Will Mary Peltola win the 2026 Alaska Senate race? — Mary Peltola | Will Mary Peltola win the Alaska Senate race in 2026? | $32,501 | $164,101 | central | 524.6 | 0.653 |  |
| KXSEOULMAYOR-26JUN03-OSEH | Will Oh Se-hoon win the 2026 Seoul mayoral election? — Oh Se-hoon | Will Oh Se-hoon win the 2026 Seoul Mayoral Election | $46,736 | $2,187,224 | mid_low | 371.5 | 0.653 |  |
| KXTARIFFCHECKS-26-27 | Will it be reported that at least one million Americans have received… | Will Monero hit $1000 in 2026? | $864,963 | $100,182 | mid_low | 218.1 | 0.650 |  |
| KXARODGRETIRE-26 | Will Aaron Rodgers announce their retirement in 2026? — Before the st… | Will Aaron Rodgers retire before next season? | $136,861 | $170,593 | tail_low | 99.5 | 0.643 |  |
| KXPERUPRES-26-KFUJ | Who will win the next Peruvian presidential election? — Keiko Fujimori | Will Keiko Fujimori win the 2026 Peruvian presidential election? | $696,416 | $6,977,278 | mid_high | 319.5 | 0.641 |  |
| KXCOREUND-26DEC10-T2.2 | Will year-over-year Core CPI inflation for 2026 fall below 2.2%? — Yes | Will the upper bound of the target federal funds rate be 2.25% at the… | $30,805 | $73,116 | mid_low | 196.5 | 0.641 |  |
| KXTRUMPNBAFINALS-26JUN-DJT | Will Donald Trump attend any 2026 Pro Basketball finals game in perso… | Will Roy Barreras win the 2026 Colombian presidential election? | $68,143 | $1,228,942 | mid_high | 23.5 | 0.639 |  |
| KXLAMAYOR1R-26-SPRA | Who will win the first round of the Los Angeles mayoral election? — S… | Will Spencer Pratt win the 2026 Los Angeles mayoral election? | $312,914 | $1,639,300 | mid_low | 370.5 | 0.637 |  |
| KXTARIFFCHECKS-26-JUN | Will it be reported that at least one million Americans have received… | Will one Democratic Party candidate and one Republican Party candidat… | $107,481 | $32,907 | tail_low | 4.1 | 0.636 |  |
| KXMAKERFIELDBY-27JAN01-LAB | Will Labour win the 2026 Makerfield by-election? — Labour | Will Nicolás Maduro be sentenced to less than 20 years in prison? | $25,232 | $75,240 | mid_high | 583.6 | 0.636 |  |
| KXLAMAYOR1R-26-NRAM | Who will win the first round of the Los Angeles mayoral election? — N… | Will Nithya Raman win the 2026 Los Angeles mayoral election? | $45,715 | $167,225 | tail_low | 370.5 | 0.636 |  |
| KXLBJRETIRE-26 | Will LeBron James announce his retirement in 2026? — Before the start… | Will there be another US government shutdown by January 31 and will t… | $566,310 | $51,040 | tail_low | 156.5 | 0.635 |  |
| KXCHAICUTS-26JUN04-T1 | Will “Artificial Intelligence” be the #1 reason for job cuts in Chall… | Will Park Chan-dae win the 2026 Incheon mayoral election? | $25,789 | $171,796 | mid_high | 7.3 | 0.635 |  |
| KXNBA-26-NYK | Will the New York win the 2026 Pro Basketball Finals? — New York | Will the Republicans win the New York governor race in 2026? | $29,625,319 | $39,445 | central | 763.5 | 0.634 |  |
| KXLAMAYOR1R-26-KBAS | Who will win the first round of the Los Angeles mayoral election? — K… | Will Karen Bass win the 2026 Los Angeles mayoral election? | $60,432 | $144,574 | mid_high | 370.5 | 0.634 |  |
| KXCOST-26MAYCARDS-150000000.0 | Will Costco Wholesale Corporation report above 150 million total card… | Will Keaton Verhoeff be drafted 1st overall in the 2026 NHL Draft? | $70,602 | $36,510 | tail_low | 30.8 | 0.628 |  |
| KXCOST-26MAYCARDS-149000000.0 | Will Costco Wholesale Corporation report above 149 million total card… | Will Keaton Verhoeff be drafted 1st overall in the 2026 NHL Draft? | $25,128 | $36,510 | central | 30.8 | 0.628 |  |
| KXCOST-26MAYCARDS-147000000.0 | Will Costco Wholesale Corporation report above 147 million total card… | Will Keaton Verhoeff be drafted 1st overall in the 2026 NHL Draft? | $32,002 | $36,510 | tail_high | 30.8 | 0.628 |  |
| KXNBA-26-SAS | Will the San Antonio win the 2026 Pro Basketball Finals? — San Antonio | Will the San Antonio Spurs win the 2026 NBA Finals? | $33,117,098 | $31,119,964 | mid_low | 763.5 | 0.617 |  |
| KXMAKERFIELDBY-27JAN01-RES | Will Restore Britain win the 2026 Makerfield by-election? — Restore B… | Will Nicolás Maduro be sentenced to at least 60 years in prison? | $68,996 | $35,142 | tail_low | 583.6 | 0.613 |  |
| KXTRUMPBALLROOM-28JAN01 | Will it be reported that the White House State Ballroom is completed… | Will Anthropic’s market cap be between $100B and $200B at market clos… | $29,315 | $56,158 | tail_low | 583.1 | 0.610 |  |
| KXNBA-26-OKC | Will the Oklahoma City win the 2026 Pro Basketball Finals? — Oklahoma… | Will the Oklahoma City Thunder win the 2026 NBA Finals? | $19,955,731 | $14,187,971 | central | 763.5 | 0.607 |  |
| KXHOUSEPOPVOTEMARGIN-27NOV03-B50 | Will Republicans win the 2026 U.S. House of Representatives national… | Will the Republicans win the Iowa Senate race in 2026? | $195,943 | $53,722 | mid_low | 524.5 | 0.604 |  |
| KXTARIFFCHECKS-26-JUL | Will it be reported that at least one million Americans have received… | Will Z.ai have the top AI model at the end of June 2026? | $172,941 | $419,672 | tail_low | 34.1 | 0.601 |  |
| KXTSLA-26JULPROD-440000.0 | Will Tesla Inc. report above 440000 total production in Q2 2026? — Ab… | Will Treg Taylor advance from the 2026 Alaska Governor primary electi… | $38,245 | $56,457 | central | 85.8 | 0.599 |  |
| KXTSLA-26JULPROD-420000.0 | Will Tesla Inc. report above 420000 total production in Q2 2026? — Ab… | Will Treg Taylor advance from the 2026 Alaska Governor primary electi… | $31,578 | $56,457 | central | 85.8 | 0.599 |  |
| KXTSLA-26JULDELIV-450000.0 | Will Tesla Inc. report above 450000 total deliveries in Q2 2026? — Ab… | Will Treg Taylor advance from the 2026 Alaska Governor primary electi… | $26,846 | $56,457 | mid_low | 85.8 | 0.599 |  |
| KXSENATEDEMLEAD-28JAN01-CMUR | Will Chris Murphy win the next Senate Democratic Leader election? — C… | Will the Democrats win the Maine Senate race in 2026? | $26,953 | $194,421 | tail_low | 948.6 | 0.597 |  |
| KXSEOULMAYOR-26JUN03-CWON | Will Chong Won-o win the 2026 Seoul mayoral election? — Chong Won-o | Will the Republicans win the Ohio governor race in 2026? | $83,436 | $48,162 | mid_high | 371.5 | 0.595 |  |
| KXTAKEOVERACQWB-27JUN30-PSKY | Will Paramount's takeover of Warner Brothers succeed Before July 2027… | Will Paramount close Warner Bros acquisition? | $1,447,690 | $463,411 | mid_high | 399.1 | 0.595 |  |
| KXTRUMPUFC-26JUL-DJT | Will Donald Trump attend UFC 329? — Yes | Will Sonay Kartal be the 2026 Women’s Wimbledon Winner? | $173,323 | $42,512 | mid_low | 45.5 | 0.592 |  |
| KXISRAELKNESSET-26-BEN | Will Bennett 2026 win the next Israeli legislative election? — Bennet… | Will Asia win the 2026 FIFA World Cup? | $37,962 | $351,282 | tail_low | 517.5 | 0.583 |  |
| KXIRANDEMOCRACY-27MAR01-T6 | Will Iran's score in the Economist Intelligence Unit's Democracy Inde… | Will GTA 6 cost $100+? | $235,642 | $136,835 | tail_low | 277.6 | 0.583 |  |
| KXTAKEOVERACQWB-27JUN30-NFLX | Will Netflix's takeover of Warner Brothers succeed Before July 2027?… | Will Netflix close Warner Bros acquisition? | $1,281,367 | $237,469 | tail_low | 399.1 | 0.579 |  |
| KXECONSTATCPICORE-26MAY-T0.5 | CPI core month-over-month in May 2026? — Exactly 0.5% | Will Chong Won-oh win the 2026 Seoul Mayoral Election | $28,346 | $1,387,775 | tail_low | 13.5 | 0.576 |  |
| KXECONSTATCPICORE-26MAY-T0.3 | CPI core month-over-month in May 2026? — Exactly 0.3% | Will Chong Won-oh win the 2026 Seoul Mayoral Election | $36,655 | $1,387,775 | mid_low | 13.5 | 0.576 |  |
| KXECONSTATCPICORE-26MAY-T0.0 | CPI core month-over-month in May 2026? — Exactly 0.0% | Will Chong Won-oh win the 2026 Seoul Mayoral Election | $25,686 | $1,387,775 | tail_low | 13.5 | 0.576 |  |
| KXECONSTATCPICORE-26MAY-T-0.2 | CPI core month-over-month in May 2026? — Exactly -0.2% | Will Chong Won-oh win the 2026 Seoul Mayoral Election | $47,815 | $1,387,775 | tail_low | 13.5 | 0.573 |  |
| KXECONSTATCPICORE-26MAY-T-0.1 | CPI core month-over-month in May 2026? — Exactly -0.1% | Will Chong Won-oh win the 2026 Seoul Mayoral Election | $291,587 | $1,387,775 | tail_low | 13.5 | 0.573 |  |
| KXECONSTATCPI-26JUN-T0.0 | CPI month-over-month in Jun 2026? — Exactly 0.0% | Will Clara Tauson be the 2026 Women’s Wimbledon Winner? | $145,871 | $443,185 | mid_low | 47.5 | 0.572 |  |
| KXECONSTATCPI-26JUN-T-0.2 | CPI month-over-month in Jun 2026? — Exactly -0.2% | Will Clara Tauson be the 2026 Women’s Wimbledon Winner? | $266,864 | $443,185 | tail_low | 47.5 | 0.569 |  |
| KXECONSTATCPI-26JUN-T-0.1 | CPI month-over-month in Jun 2026? — Exactly -0.1% | Will Clara Tauson be the 2026 Women’s Wimbledon Winner? | $182,385 | $443,185 | tail_low | 47.5 | 0.569 |  |
| KXTARIFFCHECKS-26-AUG | Will it be reported that at least one million Americans have received… | Will Chellie Pingree be the Democratic nominee for Senate in Maine? | $604,547 | $91,407 | tail_low | 65.1 | 0.562 |  |
| KXECONSTATCORECPIYOY-26JUL-T3.7 | CPI core year-over-year in Jul 2026? — Exactly 3.7% | Will Charity Clark win the 2026 Vermont Governor Democratic primary e… | $262,495 | $52,175 | tail_low | 76.5 | 0.557 |  |
| KXECONSTATCORECPIYOY-26JUL-T2.5 | CPI core year-over-year in Jul 2026? — Exactly 2.5% | Will Charity Clark win the 2026 Vermont Governor Democratic primary e… | $202,256 | $52,175 | tail_low | 76.5 | 0.557 |  |
| KXECONSTATCORECPIYOY-26JUL-T2.3 | CPI core year-over-year in Jul 2026? — Exactly 2.3% | Will Charity Clark win the 2026 Vermont Governor Democratic primary e… | $39,095 | $52,175 | tail_low | 76.5 | 0.557 |  |
| KXECONSTATCORECPIYOY-26JUL-T2.2 | CPI core year-over-year in Jul 2026? — Exactly 2.2% | Will Charity Clark win the 2026 Vermont Governor Democratic primary e… | $43,280 | $52,175 | tail_low | 76.5 | 0.557 |  |
| KXMAYORLA-26-SPRA | Who will win Los Angeles Mayoral Election? — Spencer Pratt | Will Spencer Pratt win the 2026 Los Angeles mayoral election? | $19,211,444 | $1,639,300 | mid_low | 370.5 | 0.553 |  |
| KXDEFGDP-26OCT20-T5 | Will U.S. federal deficit-to-GDP for FY2026 be below 5%? — Below 5% | Will LeBron James retire before next NBA season? | $54,166 | $140,424 | tail_low | 145.5 | 0.551 |  |
| KXINSOSNOMR-26-DMOR | Who will win 2026 Indiana Secretary of State Republican primary? — Di… | Will the Republicans win the Montana Senate race in 2026? | $38,409 | $38,193 | tail_low | 342.5 | 0.550 |  |
| KXMAYORLA-26-NRAM | Who will win Los Angeles Mayoral Election? — Nithya Raman | Will Nithya Raman win the 2026 Los Angeles mayoral election? | $1,968,679 | $167,225 | tail_low | 370.5 | 0.550 |  |
| KXECONSTATCORECPIYOY-26JUN-T3.6 | CPI core year-over-year in Jun 2026? — Exactly 3.6% | Will Paula Badosa be the 2026 Women’s Wimbledon Winner? | $99,282 | $83,655 | tail_low | 47.5 | 0.550 |  |
| KXECONSTATCORECPIYOY-26JUN-T3.5 | CPI core year-over-year in Jun 2026? — Exactly 3.5% | Will Paula Badosa be the 2026 Women’s Wimbledon Winner? | $235,503 | $83,655 | tail_low | 47.5 | 0.550 |  |
| KXECONSTATCORECPIYOY-26JUN-T2.3 | CPI core year-over-year in Jun 2026? — Exactly 2.3% | Will Clara Tauson be the 2026 Women’s Wimbledon Winner? | $301,514 | $443,185 | tail_low | 47.5 | 0.550 |  |
| KXECONSTATCORECPIYOY-26JUN-T2.2 | CPI core year-over-year in Jun 2026? — Exactly 2.2% | Will Clara Tauson be the 2026 Women’s Wimbledon Winner? | $32,948 | $443,185 | tail_low | 47.5 | 0.550 |  |
| KXMAYORLA-26-AMIL | Who will win Los Angeles Mayoral Election? — Adam Miller | Will Adam Miller win the 2026 Los Angeles mayoral election? | $532,320 | $174,351 | tail_low | 370.5 | 0.548 |  |
| KXMAYORLA-26-RCAR | Who will win Los Angeles Mayoral Election? — Rick Caruso | Will Rick Caruso win the 2026 Los Angeles mayoral election? | $200,451 | $484,222 | tail_low | 370.5 | 0.548 |  |
| KXMAYORLA-26-KBAS | Who will win Los Angeles Mayoral Election? — Karen Bass | Will Karen Bass win the 2026 Los Angeles mayoral election? | $2,262,569 | $144,574 | central | 370.5 | 0.545 |  |
| KXMAYORLA-26-RHUA | Who will win Los Angeles Mayoral Election? — Rae Huang | Will Rae Huang win the 2026 Los Angeles mayoral election? | $221,795 | $501,740 | tail_low | 370.5 | 0.542 |  |
| KXGOVCAPRIMARYPARTY-26-2D | Who will advance from California's top-two primary for governor? — 2… | Will the Democrats win the Rhode Island governor race in 2026? | $64,661 | $47,230 | mid_low | 370.5 | 0.531 |  |
| KXGOVCAPRIMARYPARTY-26-2R | Who will advance from California's top-two primary for governor? — 2… | Will the Republicans win the Minnesota governor race in 2026? | $147,449 | $30,732 | tail_low | 370.5 | 0.528 |  |
| KXHOUSEPOPVOTEMARGIN-27NOV03-B1 | Will the Democratic margin of victory in the 2026 U.S. House of Repre… | Will the Democratic Progressive Party (DPP) win the most head of loca… | $32,173 | $30,625 | tail_low | 524.5 | 0.524 |  |
| KXCA14SWINNER-26-AWAH | Who will win the 2026 CA-14 special election? — Aisha Wahab | Will the Republicans win the North Carolina Senate race in 2026? | $34,387 | $34,565 | tail_high | 524.6 | 0.515 |  |
| KXCA14SWINNER-26-RSIN | Who will win the 2026 CA-14 special election? — Rakhi Israni Singh | Will the Republican Party hold exactly 48 Senate seats after the 2026… | $64,132 | $37,299 | tail_low | 524.6 | 0.514 |  |
| KXTAKEOVERACQWB-27JUN30-NONE | Will None's takeover of Warner Brothers succeed Before July 2027? — N… | Ramp IPO before 2027? | $691,647 | $144,101 | mid_low | 399.1 | 0.509 |  |
| KXNFPROD-27MAR04-T3 | Will U.S. nonfarm productivity YoY in any quarter for 2026 be above 3… | Will the Democrats win the New York governor race in 2026? | $51,420 | $36,861 | central | 280.5 | 0.500 |  |
| KXCA11PERSON-26-SWIE | Who will win the CA-11 House election? — Scott Wiener | Will the Democrats win the Ohio governor race in 2026? | $29,935 | $49,137 | central | 524.6 | 0.490 | uncertain |
| KXGOVCAPRIMARYPARTY-26-1D1R | Who will advance from California's top-two primary for governor? — 1… | Will the Republicans win the Minnesota governor race in 2026? | $60,007 | $30,732 | mid_high | 370.5 | 0.488 | uncertain |
| KXGOVCAPRIMARY-26-MMAH | Who will win California's top-two primary for governor? — Matt Mahan | Will the Democrats win the Michigan governor race in 2026? | $155,036 | $41,372 | tail_low | 370.5 | 0.483 | uncertain |
| KXCA11PERSON-26-SCHA | Who will win the CA-11 House election? — Saikat Chakrabarti | Will the Republicans win the North Carolina Senate race in 2026? | $41,403 | $34,565 | tail_low | 524.6 | 0.479 | uncertain |

## Summary footer

- **Total candidates:** 96

- **By probability bucket:**
  - `tail_low`: 49
  - `mid_low`: 14
  - `central`: 18
  - `mid_high`: 12
  - `tail_high`: 3

- **By Kalshi series category:**
  - `Elections`: 47
  - `Economics`: 21
  - `Financials`: 14
  - `Politics`: 8
  - `Sports`: 6
