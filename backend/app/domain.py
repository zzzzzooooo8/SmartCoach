from typing import Any


ACTIVITY_FACTORS = {
    "sedentary": 1.2,
    "light": 1.375,
    "moderate": 1.55,
    "heavy": 1.725,
}


def build_weight_loss_plan(profile: dict[str, Any], target_loss_speed: float = 0.5) -> dict[str, Any]:
    weight = float(profile["current_weight_kg"])
    height = float(profile["height_cm"])
    age = int(profile["age"])
    gender = profile["gender"]
    factor = ACTIVITY_FACTORS[profile["activity_level"]]

    bmr = 10 * weight + 6.25 * height - 5 * age + (5 if gender == "male" else -161)
    tdee = bmr * factor
    daily_deficit = min(700.0, max(250.0, target_loss_speed * 1100.0))
    minimum = 1500.0 if gender == "male" else 1200.0
    calories = max(minimum, tdee - daily_deficit)
    protein = weight * 1.6

    return {
        "bmr": round(bmr, 2),
        "tdee": round(tdee, 2),
        "daily_calorie_target": round(calories, 2),
        "daily_protein_target": round(protein, 2),
        "target_loss_speed": target_loss_speed,
        "training_advice": "每周安排 2 至 3 次力量训练，并结合适量低到中等强度有氧。",
    }
