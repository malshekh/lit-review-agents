| Step | Model | Input byte-bound | Output cap | Uncached / 1h write / read | Cold +30% | Cache scenario +30% | Cumulative cold |
|---|---|---:|---:|---|---:|---:|---:|
| GROUP_G0001 | claude-opus-5 | 38,584 | 12,000 | 26,674/11,910/0 | $0.891592 | $0.718211 | $0.891592 |
| GROUP_G0002 | claude-opus-5 | 34,855 | 12,000 | 22,945/0/11,910 | $0.843115 | $0.546884 | $1.734707 |
| GROUP_G0003 | claude-opus-5 | 90,707 | 12,000 | 78,797/0/11,910 | $1.569191 | $0.909922 | $3.303898 |
| GROUP_G0004 | claude-opus-5 | 76,170 | 12,000 | 64,260/0/11,910 | $1.380210 | $0.815432 | $4.684108 |
| GROUP_G0005 | claude-opus-5 | 70,407 | 12,000 | 58,497/0/11,910 | $1.305291 | $0.777972 | $5.989399 |
| GROUP_G0006 | claude-opus-5 | 65,302 | 12,000 | 53,392/0/11,910 | $1.238926 | $0.744789 | $7.228325 |
| GROUP_G0007 | claude-opus-5 | 82,270 | 12,000 | 70,360/0/11,910 | $1.459510 | $0.855082 | $8.687835 |
| GROUP_G0008 | claude-opus-5 | 70,692 | 12,000 | 58,782/0/11,910 | $1.308996 | $0.779825 | $9.996831 |
| GROUP_G0009 | claude-opus-5 | 72,968 | 12,000 | 61,058/0/11,910 | $1.338584 | $0.794619 | $11.335415 |
| GROUP_G0010 | claude-opus-5 | 34,373 | 12,000 | 22,463/0/11,910 | $0.836849 | $0.543751 | $12.172264 |
| GROUP_G0011 | claude-opus-5 | 27,495 | 12,000 | 15,585/0/11,910 | $0.747435 | $0.499044 | $12.919699 |
| RECONCILE_0001 | claude-opus-5 | 246,670 | 6,000 | 234,760/0/11,910 | $3.401710 | $1.728681 | $16.321409 |
| RECONCILE_0002 | claude-opus-5 | 265,593 | 6,000 | 253,683/0/11,910 | $3.647709 | $1.851681 | $19.969118 |
| RECONCILE_0003 | claude-opus-5 | 265,253 | 6,000 | 253,343/0/11,910 | $3.643289 | $1.849471 | $23.612407 |
| RECONCILE_0004 | claude-opus-5 | 250,310 | 6,000 | 238,400/0/11,910 | $3.449030 | $1.752341 | $27.061437 |
| RECONCILE_0005 | claude-opus-5 | 213,359 | 6,000 | 201,449/0/11,910 | $2.968667 | $1.512160 | $30.030104 |
| FINAL | claude-opus-5 | 371,123 | 6,000 | 359,213/0/11,910 | $5.019599 | $2.537626 | $35.049703 |
| A08_outline | gpt-6.1-sol | 384,785 | 8,000 | 384,785/0/0 | $2.156882 | $2.156882 | $37.206585 |
| A09_section_1 | claude-opus-5 | 648,186 | 2,500 | 648,186/0/0 | $8.507668 | $4.294459 | $45.714253 |
| A09_section_2 | claude-opus-5 | 660,186 | 2,500 | 660,186/0/0 | $8.663668 | $4.372459 | $54.377921 |
| A09_front_matter | claude-opus-5 | 78,820 | 8,000 | 78,820/0/0 | $1.284660 | $0.772330 | $55.662581 |

- All input token figures are conservative serialized-byte bounds, not provider counts. No network used.
- Only the system prefix is cached in v10 A07. No hit guarantee; actual admission must cold-price every call.
- Future reconciliation, final, A08 and A09 inputs are conditional projections, not actual requests or certified worst-case bounds.
- 2500 A09 tokens share adaptive thinking at high effort: insufficient demonstrated text headroom. No guarantee of 400-500 words plus JSON/bindings.
- Front matter is required by native writer; cannot omit this paid call silently.
- No holds placed, no financial fingerprint changed, no PLAN acceptance or checkpoint approval.
- No verified GROUP command exists for consumed PLAN-only v10 launcher.

- {"kind": "A07 GROUP retrieval", "additional_calls_up_to": 22, "basis": "Each actual lookup request must be rebuilt and cold-reserved with up to 12 new finding IDs/round; not included in base path; no automatic lookup authorized."}
- {"kind": "A07 RECONCILE retrieval", "additional_calls_up_to": 10, "basis": "Source-grounded reconciliation issues require retrieved anchors; zero-lookup base can stop NEEDS_EVIDENCE. Budget re-review then required."}
- {"kind": "A09 evidence retrieval", "additional_calls_up_to": 4, "basis": "Two rounds for each of two sections under frozen config; no retrieval authorized in sample base; reprice actual payload."}
- {"kind": "JSON repair / truncation retry", "additional_calls": 0, "basis": "No automatic repair or retries. Separately authorize and reserve any exact repair request after failure."}

## Additional retrieval contingency calls (excluded from base; no authorization)

| Step | Input bound | Output cap | Cold cost | With 30% |
|---|---:|---:|---:|---:|
| GROUP_G0001_LOOKUP1 | 101,282 | 12,000 | $1.312820 | $1.706666 |
| GROUP_G0001_LOOKUP2 | 157,560 | 12,000 | $1.875600 | $2.438280 |
| GROUP_G0002_LOOKUP1 | 97,553 | 12,000 | $1.275530 | $1.658189 |
| GROUP_G0002_LOOKUP2 | 153,831 | 12,000 | $1.838310 | $2.389803 |
| GROUP_G0003_LOOKUP1 | 153,405 | 12,000 | $1.834050 | $2.384265 |
| GROUP_G0003_LOOKUP2 | 209,683 | 12,000 | $2.396830 | $3.115879 |
| GROUP_G0004_LOOKUP1 | 138,868 | 12,000 | $1.688680 | $2.195284 |
| GROUP_G0004_LOOKUP2 | 195,146 | 12,000 | $2.251460 | $2.926898 |
| GROUP_G0005_LOOKUP1 | 133,105 | 12,000 | $1.631050 | $2.120365 |
| GROUP_G0005_LOOKUP2 | 189,383 | 12,000 | $2.193830 | $2.851979 |
| GROUP_G0006_LOOKUP1 | 128,000 | 12,000 | $1.580000 | $2.054000 |
| GROUP_G0006_LOOKUP2 | 184,278 | 12,000 | $2.142780 | $2.785614 |
| GROUP_G0007_LOOKUP1 | 144,968 | 12,000 | $1.749680 | $2.274584 |
| GROUP_G0007_LOOKUP2 | 201,246 | 12,000 | $2.312460 | $3.006198 |
| GROUP_G0008_LOOKUP1 | 133,390 | 12,000 | $1.633900 | $2.124070 |
| GROUP_G0008_LOOKUP2 | 189,668 | 12,000 | $2.196680 | $2.855684 |
| GROUP_G0009_LOOKUP1 | 135,666 | 12,000 | $1.656660 | $2.153658 |
| GROUP_G0009_LOOKUP2 | 191,944 | 12,000 | $2.219440 | $2.885272 |
| GROUP_G0010_LOOKUP1 | 97,071 | 12,000 | $1.270710 | $1.651923 |
| GROUP_G0010_LOOKUP2 | 153,349 | 12,000 | $1.833490 | $2.383537 |
| GROUP_G0011_LOOKUP1 | 90,193 | 12,000 | $1.201930 | $1.562509 |
| GROUP_G0011_LOOKUP2 | 146,471 | 12,000 | $1.764710 | $2.294123 |
| RECONCILE_0001_LOOKUP1 | 309,368 | 6,000 | $3.243680 | $4.216784 |
| RECONCILE_0001_LOOKUP2 | 365,646 | 6,000 | $3.806460 | $4.948398 |
| RECONCILE_0002_LOOKUP1 | 328,291 | 6,000 | $3.432910 | $4.462783 |
| RECONCILE_0002_LOOKUP2 | 384,569 | 6,000 | $3.995690 | $5.194397 |
| RECONCILE_0003_LOOKUP1 | 327,951 | 6,000 | $3.429510 | $4.458363 |
| RECONCILE_0003_LOOKUP2 | 384,229 | 6,000 | $3.992290 | $5.189977 |
| RECONCILE_0004_LOOKUP1 | 313,008 | 6,000 | $3.280080 | $4.264104 |
| RECONCILE_0004_LOOKUP2 | 369,286 | 6,000 | $3.842860 | $4.995718 |
| RECONCILE_0005_LOOKUP1 | 276,057 | 6,000 | $2.910570 | $3.783741 |
| RECONCILE_0005_LOOKUP2 | 332,335 | 6,000 | $3.473350 | $4.515355 |

Bounds add largest per-finding detail sizes and overcount shared contexts. No automatic lookup/repair is authorized. A09 additional calls and error-specific repair requests require actual packet/error construction; no numerical bound is certified for these unknown requests.
