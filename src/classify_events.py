import re
import pandas as pd


INPUT_FILE = (
    "data/processed/notes_normalized.csv"
)

OUTPUT_FILE = (
    "data/processed/notes_events.csv"
)


def classify_event(row):

    role = str(
        row["author_role"]
    ).lower()

    text = str(
        row["normalized_text"]
    ).lower()


    if (
        "physical therapist" in role
        or "pt visit" in text
        or "therapy session" in text
        or "rehab note" in text
    ):

        return "PhysicalTherapy"


    if (
        "treating provider" in role
        or "office note" in text
        or "dr note" in text
    ):

        return "Medical"


    if "nurse" in role:

        return "NurseCaseManagement"


    if (
        "ime" in text
        or
        "independent medical examination"
        in text
    ):

        return "IME"


    if (
        "hearing" in text
        or "conciliation" in text
        or "board notice" in text
    ):

        return "LegalHearing"


    if (
        "work status" in text
        or "return to work" in text
        or "light duty" in text
        or "modified duty" in text
        or "off work" in text
    ):

        return "WorkStatus"


    if (
        "compensability" in text
        or "accepting as work related"
        in text
        or "disputing for now"
        in text
    ):

        return "ClaimDecision"


    if (
        "xray" in text
        or "mri" in text
        or "imaging" in text
    ):

        return "Imaging"


    if (
        "pharmacy" in text
        or "rx check" in text
    ):

        return "Pharmacy"


    if (
        "bill review" in text
        or "payment" in text
        or "ledger" in text
    ):

        return "PaymentBilling"


    if "supervisor" in role:

        return "EmployerSupervisor"


    if "adjuster" in role:

        return "AdjusterActivity"


    if "assistant" in role:

        return "Administrative"


    return "Other"


def main():

    df = pd.read_csv(
        INPUT_FILE
    )

    df["event_type"] = (
        df.apply(
            classify_event,
            axis=1
        )
    )

    print(
        df["event_type"]
        .value_counts()
    )

    df.to_csv(
        OUTPUT_FILE,
        index=False
    )


if __name__ == "__main__":

    main()