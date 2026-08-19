"""Primary readout for a randomised open-label trial. n=840, 1:1 allocation."""
import pandas as pd
from scipy import stats

SUBGROUPS = ["age_band", "sex", "prior_therapy", "region",
             "baseline_severity", "smoker", "diabetes", "site_volume"]


def readout(path: str) -> dict:
    df = pd.read_csv(path)
    df = df[df["completed_followup"]]

    arm_a = df[df["arm"] == "A"]
    arm_b = df[df["arm"] == "B"]

    t, p = stats.ttest_ind(arm_a["days_to_event"], arm_b["days_to_event"])
    primary = {"t": round(t, 3), "p": round(p, 4),
               "n_a": len(arm_a), "n_b": len(arm_b)}

    signals = []
    for column in SUBGROUPS:
        for level in sorted(df[column].dropna().unique()):
            sub = df[df[column] == level]
            a = sub[sub["arm"] == "A"]["days_to_event"]
            b = sub[sub["arm"] == "B"]["days_to_event"]
            if len(a) < 10 or len(b) < 10:
                continue
            _, sub_p = stats.ttest_ind(a, b)
            if sub_p < 0.05:
                signals.append({"subgroup": f"{column}={level}",
                                "p": round(sub_p, 4)})

    return {"primary": primary, "significant_subgroups": signals}
