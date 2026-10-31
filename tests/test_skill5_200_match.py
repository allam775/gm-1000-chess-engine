"""Score accounting must never convert incomplete or invalid games into draws."""
from scripts.skill5_200_match import summarize, outcome_label

def test_score_orientation_and_draws():
    assert outcome_label('1-0', 'white') == 'win'
    assert outcome_label('1-0', 'black') == 'loss'
    assert outcome_label('0-1', 'white') == 'loss'
    assert outcome_label('0-1', 'black') == 'win'
    assert outcome_label('1/2-1/2', 'white') == 'draw'
    assert outcome_label('*', 'black') == 'incomplete'

def test_incomplete_and_errors_never_count_as_points():
    data = [
        {'color':'white','outcome':'win'}, {'color':'black','outcome':'draw'},
        {'color':'black','outcome':'loss'}, {'color':'white','outcome':'error'},
        {'color':'black','outcome':'incomplete'},
    ]
    stats = summarize(data)
    assert stats['completed'] == 3
    assert stats['wins'] == stats['losses'] == stats['draws'] == 1
    assert stats['errors'] == stats['incomplete'] == 1
    assert stats['score_percent'] == 50.
    assert stats['by_color']['black']['completed'] == 2