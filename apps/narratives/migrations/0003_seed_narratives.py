"""Seeds a handful of starter narratives so the system isn't empty out of
the box. This is a convenience starting point, not "the final system" the
PRD warns against hardcoding -- every row here is ordinary data, freely
editable/extendable via admin or the API without a code change or migration.
"""

from django.db import migrations

SEED_NARRATIVES = [
    {
        "name": "AI Agents",
        "category": "ai",
        "keywords": ["ai", "agent", "gpt", "neural", "llm", "bot", "machine learning"],
    },
    {
        "name": "Political Meme",
        "category": "politics",
        "keywords": ["trump", "biden", "election", "president", "senate", "politic"],
    },
    {
        "name": "Gaming",
        "category": "gaming",
        "keywords": ["game", "gaming", "play2earn", "p2e", "metaverse", "rpg"],
    },
    {
        "name": "Animal Meme",
        "category": "animals",
        "keywords": ["dog", "cat", "inu", "shiba", "frog", "pepe", "wojak", "bear", "bull"],
    },
    {
        "name": "Celebrity",
        "category": "celebrity",
        "keywords": ["celebrity", "viral", "famous", "star"],
    },
]


def seed_narratives(apps, schema_editor):
    Narrative = apps.get_model("narratives", "Narrative")
    for entry in SEED_NARRATIVES:
        Narrative.objects.get_or_create(
            name=entry["name"],
            defaults={"category": entry["category"], "keywords": entry["keywords"], "is_active": True},
        )


def remove_seeded_narratives(apps, schema_editor):
    Narrative = apps.get_model("narratives", "Narrative")
    Narrative.objects.filter(name__in=[entry["name"] for entry in SEED_NARRATIVES]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("narratives", "0002_narrative_keywords"),
    ]

    operations = [
        migrations.RunPython(seed_narratives, remove_seeded_narratives),
    ]
