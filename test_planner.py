from src.retrieval.question_analyzer import analyze_question

questions = [
    "How did Chloe Nguyen's work restrictions change over time?",
    "The notes list December 15 and December 16 as the DOI. Which date is correct?",
    "Which notes support Chloe Nguyen's March work restrictions?",
    "Do Juliann Bell and Julian Bell refer to the same claimant?",
    "What did Chloe's MRI show and how did her work restrictions change afterward?",
]

for q in questions:
    print("\nQUESTION:", q)
    print(analyze_question(q))
