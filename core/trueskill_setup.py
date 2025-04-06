from trueskill import Rating, rate_1vs1, setup

class TrueSkillSystem:
    def __init__(self):
        # Custom parameters if needed
        setup(draw_probability=0)  # No draws in table tennis
        
    def create_rating(self) -> Rating:
        return Rating()
    
    def rate_match(self, rating1: Rating, rating2: Rating, winner: int):
        # Winner: 1 or 2
        if winner == 1:
            new_r1, new_r2 = rate_1vs1(rating1, rating2)
        else:
            new_r2, new_r1 = rate_1vs1(rating2, rating1)
        return new_r1, new_r2