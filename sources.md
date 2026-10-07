# Public NYS Workers' Compensation policy documents

Real, public documents published by the New York State Workers' Compensation Board (WCB). They complement the **synthetic** claim notes in `data/synthetic_notes/`.

Source index: <https://www.wcb.ny.gov/content/main/TheBoard/publications.jsp>

| Local file | Title | Type | Injury category | Source link |
|---|---|---|---|---|
| `claimant_guide.pdf` | Claimant Quick Start Guide (Claimant Information Packet) | claimant_guide | general | <https://www.wcb.ny.gov/content/main/TheBoard/ClaimantInformationPacket.pdf> |
| `employer_reporting.pdf` | Your Responsibilities as an Employer - Reporting Injury and Illness | employer_guidance | general | <https://www.wcb.ny.gov/content/main/TheBoard/EMP-TimelyReporting.pdf> |
| `back_guideline.pdf` | New York Mid and Low Back Injury Medical Treatment Guidelines | medical_treatment_guideline | back | <https://www.wcb.ny.gov/content/main/hcpp/MedicalTreatmentGuidelines/MidandLowBackInjuryMTG2021.pdf> |
| `knee_guideline.pdf` | New York Knee Injury Medical Treatment Guidelines | medical_treatment_guideline | knee | <https://www.wcb.ny.gov/content/main/hcpp/MedicalTreatmentGuidelines/KneeInjuryMTG2021.pdf> |
| `shoulder_guideline.pdf` | New York Shoulder Injury Medical Treatment Guidelines | medical_treatment_guideline | shoulder | <https://www.wcb.ny.gov/content/main/hcpp/MedicalTreatmentGuidelines/ShoulderInjuryMTG2021.pdf> |
| `hand_wrist_forearm_guideline.pdf` | New York Hand, Wrist and Forearm Injuries (including Carpal Tunnel Syndrome) | medical_treatment_guideline | hand/wrist/forearm | <https://www.wcb.ny.gov/content/main/hcpp/MedicalTreatmentGuidelines/HandWristForarmMTG2021.pdf> |
| `file_claim_fact_sheet.pdf` | What to Expect When You File a Claim - Your Workers' Compensation Benefits | claimant_fact_sheet | general | <https://www.wcb.ny.gov/content/main/TheBoard/file-claim-fact-sheet.pdf> |

## Notes
- Medical Treatment Guidelines (MTGs) are the 2021 editions, effective for dates of treatment on or after May 2, 2022.
- Full metadata (audience, edition, page count, extractable-text check, SHA-256) is in `metadata.csv` / `metadata.json`.
- Plain-text copies for ingestion are in `data/policy_docs_text/`.
- Regenerate or re-verify everything with `python scripts/fetch_policy_docs.py`.
- WCB publications are public documents; MTGs include ACOEM/ReedGroup material used by the Board with permission — cite the source link when quoting.
