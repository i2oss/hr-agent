# Evidence threshold calibration

Embedding model `BAAI/bge-small-en-v1.5`, k=5, hybrid retrieval. **T = 0.69** (lowest in-corpus top cosine 0.7005 minus 0.01, floored).

- In-corpus queries cut off by T: 0/16
- In-corpus queries with the expected § in the top 5: 16/16
- Out-of-corpus queries above T (left to the prompt's "passages don't answer → refuse"): 1/15

| id | set | query | top cosine | ≥ T | expected | in top k |
|---|---|---|---|---|---|---|
| CAL-IN-11 | in_corpus | core working hours | 0.837 | yes | RSE-HB-01#3.2, RSE-RW-01#5.1 | yes |
| CAL-IN-14 | in_corpus | new hire check-in meetings first 90 days | 0.822 | yes | RSE-ONB-01#3.1 | yes |
| CAL-IN-15 | in_corpus | how many floating holidays | 0.820 | yes | RSE-HOL-01#4 | yes |
| CAL-IN-01 | in_corpus | bereavement leave days for a grandparent | 0.819 | yes | RSE-LV-01#4 | yes |
| CAL-IN-02 | in_corpus | is jury duty paid | 0.812 | yes | RSE-LV-01#5 | yes |
| CAL-IN-13 | in_corpus | 401k employer match and vesting | 0.811 | yes | RSE-BEN-01#2.5 | yes |
| CAL-IN-12 | in_corpus | overtime approval for hourly employees | 0.797 | yes | RSE-HB-01#3.3 | yes |
| CAL-IN-08 | in_corpus | receipt required for small purchases | 0.768 | yes | RSE-EXP-01#8.1 | yes |
| CAL-IN-09 | in_corpus | business class flight approval | 0.762 | yes | RSE-EXP-01#3.1 | yes |
| CAL-IN-10 | in_corpus | accepting gifts from a supplier | 0.760 | yes | RSE-HB-01#4.3 | yes |
| CAL-IN-07 | in_corpus | mileage rate driving my own car to a site | 0.753 | yes | RSE-EXP-01#3.2 | yes |
| CAL-IN-05 | in_corpus | working on airport public wifi | 0.749 | yes | RSE-SEC-01#5.2 | yes |
| CAL-IN-03 | in_corpus | doctor's note after sick days | 0.737 | yes | RSE-LV-01#2 | yes |
| CAL-IN-04 | in_corpus | lost or stolen laptop reporting | 0.714 | yes | RSE-SEC-01#3.4 | yes |
| CAL-OUT-07 | near_miss | monthly parking subsidy at the office | 0.707 | yes | — |  |
| CAL-IN-06 | in_corpus | pasting client drawings into a public AI chatbot | 0.706 | yes | RSE-SEC-01#6.2 | yes |
| CAL-IN-16 | in_corpus | site injury near miss reporting deadline | 0.701 | yes | RSE-HB-01#5.2 | yes |
| CAL-OUT-01 | gap | pet insurance coverage | 0.676 | no | — |  |
| CAL-OUT-05 | gap | relocation package for a new hire moving to Denver | 0.667 | no | — |  |
| CAL-OUT-06 | gap | transit pass commuter benefit | 0.663 | no | — |  |
| CAL-OUT-02 | gap | stock options vesting schedule | 0.647 | no | — |  |
| CAL-OUT-15 | near_miss | car insurance quote for a new truck | 0.627 | no | — |  |
| CAL-OUT-04 | gap | sabbatical after five years of service | 0.612 | no | — |  |
| CAL-OUT-03 | gap | equity grant for engineers | 0.605 | no | — |  |
| CAL-OUT-08 | non_hr | minimum concrete cover for footing rebar | 0.595 | no | — |  |
| CAL-OUT-11 | near_miss | good lunch spots near the Denver office | 0.553 | no | — |  |
| CAL-OUT-10 | near_miss | weather in Seattle tomorrow | 0.544 | no | — |  |
| CAL-OUT-14 | non_hr | translate this email into French | 0.522 | no | — |  |
| CAL-OUT-12 | non_hr | python script to merge PDF files | 0.508 | no | — |  |
| CAL-OUT-13 | non_hr | Broncos score last night | 0.502 | no | — |  |
| CAL-OUT-09 | non_hr | AutoCAD trim command shortcut | 0.501 | no | — |  |
