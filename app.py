from flask import Flask, render_template, request, jsonify
from typing import Dict, List
import requests
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv
import os

load_dotenv()

app = Flask(__name__)

class MatchPlayAnalyzer:
    def __init__(self, api_token: str):
        self.base_url = "https://app.matchplay.events/api"
        self.headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

    def get_tournament_info(self, tournament_id: int) -> Dict:
        params = {
            "includePlayers": 1,
            "includeArenas": 1,
            "includeBanks": 1,
            "includeLocation": 1
        }
        response = requests.get(
            f"{self.base_url}/tournaments/{tournament_id}",
            headers=self.headers,
            params=params
        )
        response.raise_for_status()
        return response.json()

    def get_player_names(self, tournament_data: Dict) -> Dict[int, str]:
        return {
            player['playerId']: player['name'] 
            for player in tournament_data['data']['players']
        }

    def get_arena_names(self, tournament_data: Dict) -> Dict[int, str]:
        return {
            arena['arenaId']: arena['name']
            for arena in tournament_data['data']['arenas']
        }

    def get_game_results(self, tournament_id: int) -> List[Dict]:
        all_games = []
        page = 1
        
        while True:
            response = requests.get(
                f"{self.base_url}/tournaments/{tournament_id}/single-player-games",
                headers=self.headers,
                params={"page": page, "bestGame": 1}
            )
            response.raise_for_status()
            data = response.json()
            
            all_games.extend(data['data'])
            
            if not data['links']['next']:
                break
                
            page += 1
            
        return all_games

    def format_duration(self, seconds: int) -> str:
        minutes = seconds // 60
        remaining_seconds = seconds % 60
        return f"{minutes}min {remaining_seconds}s"

    def generate_report(self, tournament_id: int, top_scores: int = 3, 
                       qual_count: int = 8, finals_count: int = 4) -> Dict:
        tournament = self.get_tournament_info(tournament_id)
        players = self.get_player_names(tournament)
        arenas = self.get_arena_names(tournament)
        games = self.get_game_results(tournament_id)
        
        t_data = tournament['data']
        tournament_details = {
            "name": t_data['name'],
            "location": t_data.get('location', {}).get('name', 'Unknown'),
            "total_players": len(players),
            "total_machines": len(arenas),
            "total_games": len(games)
        }
        
        results = []
        for game in games:
            player_name = players.get(game['playerId'], f"Unknown ({game['playerId']})")
            machine_name = arenas.get(game['arenaId'], f"Unknown ({game['arenaId']})")
            results.append({
                'Player': player_name,
                'Machine': machine_name,
                'Score': game['score'],
                'Points': float(game['points']),
                'Duration': game['duration'] if game['duration'] else 0
            })
        
        df = pd.DataFrame(results)
        avg_times = df.groupby('Machine')['Duration'].mean().round().astype(int)
        
        machine_scores = {}
        for machine in sorted(df['Machine'].unique()):
            machine_df = df[df['Machine'] == machine].sort_values('Score', ascending=False).head(top_scores)
            avg_time = self.format_duration(avg_times[machine])
            scores = []
            for _, row in machine_df.iterrows():
                scores.append({
                    "player": row['Player'],
                    "score": f"{row['Score']:,}"
                })
            machine_scores[machine] = {
                "avg_time": avg_time,
                "scores": scores
            }
                
        qualifiers = []
        player_stats = df.groupby('Player')['Points'].sum().sort_values(ascending=False)
        for player, points in player_stats.head(qual_count).items():
            qualifiers.append({
                "player": player,
                "points": int(points)
            })
            
        finals = []
        linked_id = tournament['data'].get('linkedTournamentId')
        if linked_id:
            finals_response = requests.get(
                f"{self.base_url}/tournaments/{linked_id}/standings",
                headers=self.headers
            )
            finals_data = finals_response.json()
            finals_tournament = self.get_tournament_info(linked_id)
            finals_players = self.get_player_names(finals_tournament)
            
            positions = ['1st', '2nd', '3rd', '4th', '5th', '6th', '7th', '8th', '9th', '10th']
            for standing in finals_data[:finals_count]:
                pos = positions[standing['position']-1]
                player_name = finals_players.get(standing['playerId'], f'Unknown (ID: {standing["playerId"]})')
                finals.append({
                    "position": pos,
                    "player": player_name
                })

        return {
            "tournament": tournament_details,
            "machine_scores": machine_scores,
            "qualifiers": qualifiers,
            "finals": finals,
            "tournament_url": f"https://app.matchplay.events/tournaments/{tournament_id}/standings",
            "finals_url": f"https://app.matchplay.events/tournaments/{linked_id}/standings" if linked_id else None
        }

API_TOKEN = os.getenv('MATCHPLAY_API_TOKEN')
analyzer = MatchPlayAnalyzer(API_TOKEN)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/analyze', methods=['POST'])
def analyze():
    data = request.get_json()
    tournament_input = data['tournament_id']
    
    try:
        if 'matchplay.events' in tournament_input:
            tournament_id = int(tournament_input.split('/')[-1])
        else:
            tournament_id = int(tournament_input)
            
        report = analyzer.generate_report(
            tournament_id,
            top_scores=int(data.get('top_scores', 3)),
            qual_count=int(data.get('qual_count', 8)),
            finals_count=int(data.get('finals_count', 4))
        )
        return jsonify({"success": True, "data": report})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
