"""Example specs for the six infographic templates (apps/quality/infographic.py), with the content of the
October 2026 graphics they were modelled on. Tests render them, and they show the shape of each spec."""

EXAMPLES = {
    "steps": {
        "title": "How to Create a **Safe System of Work** in 5 Steps",
        "subtitle": "Worked example: cleaning a meat slicer on a supermarket deli counter",
        "example_label": "Slicer example",
        "steps": [
            {
                "title": "Assess the task and its hazards",
                "example": "Blade, accidental start, cleaning chemical",
            },
            {
                "title": "Decide how to control each hazard",
                "example": "Unplug, keep the guard fitted, cut-resistant gloves",
            },
            {"title": "Write down the safe method", "example": "Numbered steps, photo of the guard refit"},
            {
                "title": "Train, brief and supervise",
                "example": "Walk-through, explain back, record who was briefed",
            },
            {"title": "Monitor and review", "example": "Watch the task, ask what gets in the way"},
        ],
        "loop": "Something changed? Review the system and start again at step 1",
    },
    "decision": {
        "title": "When do you need a JSEA?",
        "subtitle": "Work down the questions before the job starts",
        "questions": [
            {
                "question": "Does the site, client or principal contractor require a JSEA?",
                "yes": "Write a JSEA. It is a condition of work.",
            },
            {
                "question": "Is the job new, changed or rarely done, or has there been an incident or near "
                "miss on it?",
                "yes": "Write a JSEA. It is good practice.",
            },
            {
                "question": "Does the job use chemicals, fuel, wash water or waste, or happen near drains, "
                "waterways, bushland or homes?",
                "yes": "Write a JSEA to cover the environmental risk.",
            },
        ],
        "fallback": "A JSA may be enough: the job has no way to affect the environment.",
        "warning": "High risk construction work? You also need a safe work method statement (SWMS) "
        "before the work starts.",
    },
    "columns": {
        "title": "Safety hazards vs environmental impacts",
        "subtitle": "The two columns every JSEA fills in for each job step",
        "columns": [
            {
                "title": "Safety hazards",
                "subtitle": "Harm to the crew",
                "items": [
                    "Falls, cuts, burns and strains",
                    "Chemical exposure",
                    "Lifting and carrying heavy loads",
                    "Noise loud enough to damage hearing",
                    "High-pressure jets and moving plant",
                    "Site conditions such as heat, rain, poor lighting and traffic",
                ],
            },
            {
                "title": "Environmental impacts",
                "subtitle": "Harm beyond the crew",
                "items": [
                    "Fuel or oil dripping onto soil",
                    "Wash water running into a stormwater drain",
                    "Dust drifting onto a neighbour's car or a creek",
                    "Noise that disturbs nearby homes",
                    "Chemicals, rags and containers in the general bin",
                    "Plants cleared or trampled beside a waterway",
                ],
            },
        ],
        "note": "Heat, rain and traffic affect the crew, so they go in the safety column. "
        "The environmental column "
        "is for the job's effect on the world around it.",
    },
    "part_to_whole": {
        "title": "Most hazards are missed before work starts",
        "subtitle": "Share of the hazards a crew faces during a job",
        "segments": [
            {"value": 45, "label": "Spotted in the pre-job briefing"},
            {"value": 35, "label": "Missed through blind spots"},
            {"value": 20, "label": "Can't be seen until work starts"},
        ],
        "bracket": {"segment": 2, "text": "What the FLHA catches at the work area"},
        "source": "Hallowell, Professional Safety, December 2021 (field data from 4,800 worker-hours "
        "across 12 trades).",
    },
    "bars": {
        "title": "Contributing factors in 100 construction accidents",
        "subtitle": "Share of accidents in which each factor was involved. "
        "Bars add to more than 100% because most "
        "accidents had several causes.",
        "bars": [
            {"label": "Risk management shortcomings", "value": 84},
            {"label": "Worker or work team", "value": 70},
            {"label": "Equipment, including PPE", "value": 56},
            {"label": "Workplace", "value": 49},
            {"label": "Materials", "value": 27},
        ],
        "source": "Haslam et al. (2005), Applied Ergonomics 36(4), 401-415.",
    },
    "form_anatomy": {
        "title": "What a JSEA form includes",
        "subtitle": "The nine parts of a job safety and environmental analysis form",
        "form_title": "Job safety and environmental analysis",
        "parts": [
            {"name": "Job details", "description": "Task, location, date, crew leader and crew"},
            {
                "name": "Permits and licences",
                "description": "Work permits, high risk work licences and any SWMS",
            },
            {"name": "Job steps", "description": "The main actions of the job, in order"},
            {
                "name": "Hazards and impacts",
                "description": "Separate columns for harm to people and to the environment",
                "widget": {"type": "split", "items": ["Safety hazards", "Environmental impacts"]},
            },
            {
                "name": "Risk rating",
                "description": "A score before controls and a score after",
                "widget": {"type": "chips", "items": ["Before", "After"]},
            },
            {"name": "Controls and owner", "description": "Specific controls, each with one named owner"},
            {"name": "PPE", "description": "The exact protective equipment for each job step"},
            {
                "name": "Emergency and spill plan",
                "description": "Spill kit location, first aid and who to call",
            },
            {
                "name": "Sign-on and review",
                "description": "Crew signatures, supervisor check and changes during the job",
            },
        ],
    },
}
