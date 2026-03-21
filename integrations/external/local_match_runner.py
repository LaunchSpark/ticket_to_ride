from ticket_to_ride.engine.player import Player
from ticket_to_ride.engine.game import Game
from ticket_to_ride.engine.state.game_context import GameContext
from ticket_to_ride.logging.game_logger import GameLogger
from external.clients.bot_api.loader import BotLoader
from external.clients.python.api_interface import ApiBotInterface
from typing import List

def load_bots() -> dict:
    """Load bot descriptors from the shared plugin loader."""
    loader = BotLoader()
    return loader.load_bots()




def main():
    """Entry point for running a full match via the command line."""
    players, logger = setup()
    logger.start_match("-".join([p.name for p in players]))
    round_number = 0
    round_limit = 10 # Can be changed to adjust how many consecutive rounds to run before the program stops
    
    while (round_number < round_limit):
        logger.start_round(round_number)
        
        # Initialize GameContext
        context = GameContext([p.player_id for p in players])
        game = Game(context, players, logger, round_number)
        print(f"Starting round {round_number}")
        game.play()

        round_number += 1
        if round_number != round_limit:
            players = [Player(p.player_id, p.get_interface(), p.name, p.color) for p in players]
            logger.set_player_list(players)

    logger.finalize_match()

def setup() -> 'tuple[List[Player],GameLogger]':
    """Gather setup information and instantiate all players."""
    print("=== Game Setup ===")


    while True:
        try:
            player_count = int(input("Enter number of players: "))
            if 0 <= player_count <= 4:
                break
        except ValueError:
            pass
        print("Invalid input. Please enter a non-negative integer 1-4.")

    player_ids = []
    players = []
    player_names = [
        "test_1",
        "test_2",
        "test_3",
        "test_4",
    ]
    player_colors = [
        "red",
        "blue",
        "green",
        "yellow"
    ]

    available_bots = load_bots()
    bot_descriptors = sorted(
        available_bots.values(),
        key=lambda descriptor: (descriptor.metadata.name.casefold(), descriptor.bot_id.casefold()),
    )

    for i in range(player_count):
        player_id = f"bot_{i}"
        print(f"Select bot for player {i+1}:")
        for idx, descriptor in enumerate(bot_descriptors, start=1):
            print(f"  {idx}. {descriptor.metadata.name} ({descriptor.bot_id})")
        while True:
            try:
                choice = int(input("Enter choice number: ")) - 1
                if 0 <= choice < len(bot_descriptors):
                    break
            except ValueError:
                pass
            print("Invalid choice. Please try again.")

        bot_id = bot_descriptors[choice].bot_id
        players.append(Player(player_id, ApiBotInterface(bot_id), player_names[i], player_colors[i]))

        # for the game context
        player_ids.append(player_id)

    # Initialize logger and round_number counter
    logger = GameLogger(players)

    return (players, logger)
    

if __name__ == "__main__":
    main()
