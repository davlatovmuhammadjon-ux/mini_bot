import sqlite3
from datetime import datetime

DB_NAME = "football.db"


def get_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS teams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            logo TEXT)""")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS players (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            team_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE)""")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS tournaments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            type TEXT NOT NULL CHECK(type IN ('league','cup','amateur')),
            subtype TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL)""")
    # Миграция для старых баз
    cur.execute("PRAGMA table_info(tournaments)")
    cols = [r[1] for r in cur.fetchall()]
    if "subtype" not in cols:
        cur.execute("ALTER TABLE tournaments ADD COLUMN subtype TEXT")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS tournament_teams (
            tournament_id INTEGER NOT NULL,
            team_id INTEGER NOT NULL,
            PRIMARY KEY (tournament_id, team_id),
            FOREIGN KEY (tournament_id) REFERENCES tournaments(id) ON DELETE CASCADE,
            FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE)""")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tournament_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            FOREIGN KEY (tournament_id) REFERENCES tournaments(id) ON DELETE CASCADE)""")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS group_teams (
            group_id INTEGER NOT NULL,
            team_id INTEGER NOT NULL,
            PRIMARY KEY (group_id, team_id),
            FOREIGN KEY (group_id) REFERENCES groups(id) ON DELETE CASCADE)""")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tournament_id INTEGER NOT NULL,
            group_id INTEGER,
            stage TEXT NOT NULL DEFAULT 'regular',
            home_team_id INTEGER NOT NULL,
            away_team_id INTEGER NOT NULL,
            home_score INTEGER,
            away_score INTEGER,
            date TEXT NOT NULL,
            stadium TEXT,
            FOREIGN KEY (tournament_id) REFERENCES tournaments(id) ON DELETE CASCADE,
            FOREIGN KEY (home_team_id) REFERENCES teams(id) ON DELETE CASCADE,
            FOREIGN KEY (away_team_id) REFERENCES teams(id) ON DELETE CASCADE)""")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id INTEGER NOT NULL,
            player_id INTEGER NOT NULL,
            team_id INTEGER NOT NULL,
            FOREIGN KEY (match_id) REFERENCES matches(id) ON DELETE CASCADE,
            FOREIGN KEY (player_id) REFERENCES players(id) ON DELETE CASCADE)""")

    cur.execute("CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY)")
    cur.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")

    # Миграции
    cur.execute("PRAGMA table_info(teams)")
    if "logo" not in [r[1] for r in cur.fetchall()]:
        cur.execute("ALTER TABLE teams ADD COLUMN logo TEXT")
    cur.execute("PRAGMA table_info(matches)")
    cols = [r[1] for r in cur.fetchall()]
    if "stadium" not in cols:
        cur.execute("ALTER TABLE matches ADD COLUMN stadium TEXT")
    if "tournament_id" not in cols:
        cur.execute("ALTER TABLE matches ADD COLUMN tournament_id INTEGER")
    if "group_id" not in cols:
        cur.execute("ALTER TABLE matches ADD COLUMN group_id INTEGER")
    if "stage" not in cols:
        cur.execute("ALTER TABLE matches ADD COLUMN stage TEXT DEFAULT 'regular'")

    conn.commit()

    # Создаём «Общий турнир», если турниров нет
    cur.execute("SELECT COUNT(*) AS c FROM tournaments")
    if cur.fetchone()["c"] == 0:
        cur.execute("INSERT INTO tournaments (name, type, status, created_at) VALUES (?, 'league', 'active', ?)",
                    ("Общий чемпионат", datetime.now().strftime("%Y-%m-%d %H:%M")))
        tid = cur.lastrowid
        # Привязываем все существующие команды
        cur.execute("SELECT id FROM teams")
        for row in cur.fetchall():
            cur.execute("INSERT OR IGNORE INTO tournament_teams (tournament_id, team_id) VALUES (?, ?)",
                        (tid, row["id"]))
        # Привязываем старые матчи к общему турниру
        cur.execute("UPDATE matches SET tournament_id = ?, stage = 'regular' WHERE tournament_id IS NULL", (tid,))
        conn.commit()
    conn.close()


# ================== ТУРНИРЫ ==================
def get_active_tournament():
    conn = get_connection()
    row = conn.execute("SELECT * FROM tournaments WHERE status='active' ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    return row


def get_tournaments():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM tournaments ORDER BY id DESC").fetchall()
    conn.close()
    return rows


def get_tournament(tid):
    conn = get_connection()
    row = conn.execute("SELECT * FROM tournaments WHERE id=?", (tid,)).fetchone()
    conn.close()
    return row


def create_tournament(name, type_, subtype=None):
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO tournaments (name, type, subtype, status, created_at) VALUES (?,?,?, 'active', ?)",
        (name, type_, subtype, datetime.now().strftime("%Y-%m-%d %H:%M")))
    tid = cur.lastrowid
    conn.commit()
    conn.close()
    return tid


def set_tournament_status(tid, status):
    conn = get_connection()
    conn.execute("UPDATE tournaments SET status=? WHERE id=?", (status, tid))
    conn.commit()
    conn.close()


def delete_tournament(tid):
    conn = get_connection()
    conn.execute("DELETE FROM tournaments WHERE id=?", (tid,))
    conn.commit()
    conn.close()


def get_tournament_teams(tid):
    conn = get_connection()
    rows = conn.execute("""
        SELECT t.* FROM teams t
        JOIN tournament_teams tt ON tt.team_id = t.id
        WHERE tt.tournament_id = ?
        ORDER BY t.name""", (tid,)).fetchall()
    conn.close()
    return rows


def add_team_to_tournament(tid, team_id):
    conn = get_connection()
    try:
        conn.execute("INSERT OR IGNORE INTO tournament_teams (tournament_id, team_id) VALUES (?,?)",
                     (tid, team_id))
        conn.commit()
        conn.close()
        return True
    except Exception:
        conn.close()
        return False


def remove_team_from_tournament(tid, team_id):
    conn = get_connection()
    conn.execute("DELETE FROM tournament_teams WHERE tournament_id=? AND team_id=?", (tid, team_id))
    conn.commit()
    conn.close()


def add_team(name):
    conn = get_connection()
    try:
        cur = conn.execute("INSERT INTO teams (name) VALUES (?)", (name,))
        team_id = cur.lastrowid
        # автоматически добавляем в активный турнир
        t = conn.execute("SELECT id FROM tournaments WHERE status='active' ORDER BY id DESC LIMIT 1").fetchone()
        if t:
            conn.execute("INSERT INTO tournament_teams (tournament_id, team_id) VALUES (?,?)",
                         (t["id"], team_id))
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        conn.close()
        return False


def get_teams():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM teams ORDER BY name").fetchall()
    conn.close()
    return rows


def get_team(name):
    conn = get_connection()
    row = conn.execute("SELECT * FROM teams WHERE name=?", (name,)).fetchone()
    conn.close()
    return row


def get_team_by_id(team_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM teams WHERE id=?", (team_id,)).fetchone()
    conn.close()
    return row


def delete_team_by_id(team_id):
    conn = get_connection()
    row = conn.execute("SELECT name FROM teams WHERE id=?", (team_id,)).fetchone()
    if not row:
        conn.close()
        return None
    name = row["name"]
    conn.execute("DELETE FROM matches WHERE home_team_id=? OR away_team_id=?", (team_id, team_id))
    conn.execute("DELETE FROM players WHERE team_id=?", (team_id,))
    conn.execute("DELETE FROM tournament_teams WHERE team_id=?", (team_id,))
    conn.execute("DELETE FROM group_teams WHERE team_id=?", (team_id,))
    conn.execute("DELETE FROM teams WHERE id=?", (team_id,))
    conn.commit()
    conn.close()
    return name


def set_team_logo(team_id, path):
    conn = get_connection()
    conn.execute("UPDATE teams SET logo=? WHERE id=?", (path, team_id))
    conn.commit()
    conn.close()


def clear_team_logo(team_id):
    conn = get_connection()
    conn.execute("UPDATE teams SET logo=NULL WHERE id=?", (team_id,))
    conn.commit()
    conn.close()


# ================== ИГРОКИ ==================
def add_player(team_id, name):
    conn = get_connection()
    conn.execute("INSERT INTO players (team_id, name) VALUES (?,?)", (team_id, name))
    conn.commit()
    conn.close()


def get_players(team_id):
    conn = get_connection()
    rows = conn.execute("SELECT * FROM players WHERE team_id=? ORDER BY name", (team_id,)).fetchall()
    conn.close()
    return rows


def delete_player_by_id(player_id):
    conn = get_connection()
    row = conn.execute("SELECT name FROM players WHERE id=?", (player_id,)).fetchone()
    name = row["name"] if row else None
    if row:
        conn.execute("DELETE FROM players WHERE id=?", (player_id,))
        conn.commit()
    conn.close()
    return name


# ================== МАТЧИ ==================
def add_match(tid, home_id, away_id, hs, as_, date, stadium=None, group_id=None, stage="regular"):
    conn = get_connection()
    cur = conn.execute("""
        INSERT INTO matches (tournament_id, group_id, stage, home_team_id, away_team_id,
                             home_score, away_score, date, stadium)
        VALUES (?,?,?,?,?,?,?,?,?)""",
        (tid, group_id, stage, home_id, away_id, hs, as_, date, stadium))
    mid = cur.lastrowid
    conn.commit()
    conn.close()
    return mid


def add_fixture(tid, home_id, away_id, date, stadium=None, group_id=None, stage="regular"):
    conn = get_connection()
    cur = conn.execute("""
        INSERT INTO matches (tournament_id, group_id, stage, home_team_id, away_team_id,
                             home_score, away_score, date, stadium)
        VALUES (?,?,?,?,?,NULL,NULL,?,?)""",
        (tid, group_id, stage, home_id, away_id, date, stadium))
    mid = cur.lastrowid
    conn.commit()
    conn.close()
    return mid


def set_match_score(match_id, hs, as_):
    conn = get_connection()
    conn.execute("UPDATE matches SET home_score=?, away_score=? WHERE id=?", (hs, as_, match_id))
    conn.commit()
    conn.close()


def get_match(match_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM matches WHERE id=?", (match_id,)).fetchone()
    conn.close()
    return row


def get_played_matches(tid):
    conn = get_connection()
    rows = conn.execute("""
        SELECT m.id, m.home_score, m.away_score, m.date, m.stadium, m.stage,
               ht.name AS home_name, at.name AS away_name
        FROM matches m
        JOIN teams ht ON m.home_team_id = ht.id
        JOIN teams at ON m.away_team_id = at.id
        WHERE m.home_score IS NOT NULL AND m.tournament_id = ?
        ORDER BY m.date DESC""", (tid,)).fetchall()
    conn.close()
    return rows


def get_upcoming_matches(tid):
    conn = get_connection()
    rows = conn.execute("""
        SELECT m.id, m.date, m.stadium, m.stage, ht.name AS home_name, at.name AS away_name
        FROM matches m
        JOIN teams ht ON m.home_team_id = ht.id
        JOIN teams at ON m.away_team_id = at.id
        WHERE m.home_score IS NULL AND m.tournament_id = ?
        ORDER BY m.date ASC""", (tid,)).fetchall()
    conn.close()
    return rows


def delete_match(match_id):
    conn = get_connection()
    cur = conn.execute("DELETE FROM matches WHERE id=?", (match_id,))
    conn.commit()
    conn.close()
    return cur.rowcount > 0


# ================== ГОЛЫ ==================
def add_goal(match_id, player_id, team_id):
    conn = get_connection()
    conn.execute("INSERT INTO goals (match_id, player_id, team_id) VALUES (?,?,?)",
                 (match_id, player_id, team_id))
    conn.commit()
    conn.close()


def count_goals_for_match_team(match_id, team_id):
    conn = get_connection()
    row = conn.execute("SELECT COUNT(*) AS c FROM goals WHERE match_id=? AND team_id=?",
                       (match_id, team_id)).fetchone()
    conn.close()
    return row["c"]


def get_goals_for_match(match_id):
    conn = get_connection()
    rows = conn.execute("""
        SELECT p.name AS player, t.name AS team
        FROM goals g JOIN players p ON g.player_id=p.id JOIN teams t ON p.team_id=t.id
        WHERE g.match_id=?""", (match_id,)).fetchall()
    conn.close()
    return rows


def get_top_scorers(tid, limit=15):
    conn = get_connection()
    rows = conn.execute("""
        SELECT p.name AS player, t.name AS team, COUNT(g.id) AS goals
        FROM goals g
        JOIN players p ON g.player_id=p.id
        JOIN teams t ON p.team_id=t.id
        JOIN matches m ON g.match_id=m.id
        WHERE m.tournament_id=?
        GROUP BY g.player_id ORDER BY goals DESC LIMIT ?""", (tid, limit)).fetchall()
    conn.close()
    return rows


# ================== АДМИНЫ ==================
def add_admin(user_id):
    conn = get_connection()
    conn.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()


def remove_admin(user_id):
    conn = get_connection()
    conn.execute("DELETE FROM admins WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()


def get_admins():
    conn = get_connection()
    rows = conn.execute("SELECT user_id FROM admins ORDER BY user_id").fetchall()
    conn.close()
    return rows


def is_admin(user_id):
    conn = get_connection()
    row = conn.execute("SELECT 1 FROM admins WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return row is not None


def get_owner():
    conn = get_connection()
    row = conn.execute("SELECT value FROM meta WHERE key='owner_id'").fetchone()
    conn.close()
    return int(row["value"]) if row else None


def set_owner(user_id):
    conn = get_connection()
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('owner_id',?)", (str(user_id),))
    conn.commit()
    conn.close()


# ================== ГРУППЫ (кубок) ==================
def create_group(tid, name):
    conn = get_connection()
    cur = conn.execute("INSERT INTO groups (tournament_id, name) VALUES (?,?)", (tid, name))
    gid = cur.lastrowid
    conn.commit()
    conn.close()
    return gid


def get_groups(tid):
    conn = get_connection()
    rows = conn.execute("SELECT * FROM groups WHERE tournament_id=? ORDER BY name", (tid,)).fetchall()
    conn.close()
    return rows


def get_group(gid):
    conn = get_connection()
    row = conn.execute("SELECT * FROM groups WHERE id=?", (gid,)).fetchone()
    conn.close()
    return row


def delete_groups_for_tournament(tid):
    conn = get_connection()
    conn.execute("DELETE FROM groups WHERE tournament_id=?", (tid,))
    conn.commit()
    conn.close()


def add_team_to_group(gid, team_id):
    conn = get_connection()
    conn.execute("INSERT OR IGNORE INTO group_teams (group_id, team_id) VALUES (?,?)", (gid, team_id))
    conn.commit()
    conn.close()


def get_group_teams(gid):
    conn = get_connection()
    rows = conn.execute("""
        SELECT t.* FROM teams t
        JOIN group_teams gt ON gt.team_id = t.id
        WHERE gt.group_id = ?
        ORDER BY t.name""", (gid,)).fetchall()
    conn.close()
    return rows


def get_team_group(tid, team_id):
    conn = get_connection()
    row = conn.execute("""
        SELECT g.* FROM groups g
        JOIN group_teams gt ON gt.group_id = g.id
        WHERE g.tournament_id = ? AND gt.team_id = ?""", (tid, team_id)).fetchone()
    conn.close()
    return row


# ================== ТАБЛИЦА ==================
def get_standings(tid, group_id=None):
    conn = get_connection()
    tournament = conn.execute("SELECT * FROM tournaments WHERE id=?", (tid,)).fetchone()
    if not tournament:
        conn.close()
        return []
    
    teams = conn.execute("SELECT * FROM teams").fetchall()
    if group_id:
        matches = conn.execute("""
            SELECT * FROM matches
            WHERE tournament_id=? AND group_id=? AND home_score IS NOT NULL""",
            (tid, group_id)).fetchall()
        group_team_ids = [r["team_id"] for r in conn.execute(
            "SELECT team_id FROM group_teams WHERE group_id=?", (group_id,)).fetchall()]
    else:
        matches = conn.execute("""
            SELECT * FROM matches
            WHERE tournament_id=? AND stage='regular' AND home_score IS NOT NULL""",
            (tid,)).fetchall()
        group_team_ids = [r["team_id"] for r in conn.execute(
            "SELECT team_id FROM tournament_teams WHERE tournament_id=?", (tid,)).fetchall()]
    conn.close()

    table = {}
    for t in teams:
        if t["id"] not in group_team_ids:
            continue
        table[t["id"]] = {
            "name": t["name"], "logo": t["logo"], "played": 0, 
            "wins": 0, "draws": 0, "losses": 0, 
            "gf": 0, "ga": 0, "points": 0,
            "win_pct": 0.0  # процент побед для amateur
        }
    
    for m in matches:
        h, a = m["home_team_id"], m["away_team_id"]
        if h not in table or a not in table:
            continue
        hs, as_ = m["home_score"], m["away_score"]
        table[h]["played"] += 1
        table[a]["played"] += 1
        table[h]["gf"] += hs
        table[h]["ga"] += as_
        table[a]["gf"] += as_
        table[a]["ga"] += hs
        
        if hs > as_:
            table[h]["wins"] += 1
            table[h]["points"] += 3
            table[a]["losses"] += 1
        elif hs < as_:
            table[a]["wins"] += 1
            table[a]["points"] += 3
            table[h]["losses"] += 1
        else:
            table[h]["draws"] += 1
            table[a]["draws"] += 1
            table[h]["points"] += 1
            table[a]["points"] += 1
    
    # Считаем процент побед для amateur турниров
    if tournament["type"] == "amateur":
        for tid_key in table:
            if table[tid_key]["played"] > 0:
                wins = table[tid_key]["wins"]
                played = table[tid_key]["played"]
                table[tid_key]["win_pct"] = wins / played
            else:
                table[tid_key]["win_pct"] = 0.0
    
    # Сортировка зависит от типа турнира
    if tournament["type"] == "amateur":
        # Для любительского: по проценту побед (убывание), потом по разнице мячей, потом по забитым
        return sorted(table.values(), 
                      key=lambda x: (-x["win_pct"], -(x["gf"] - x["ga"]), -x["gf"]))
    else:
        # Для обычных: по очкам, потом по разнице мячей, потом по забитым
        return sorted(table.values(), 
                      key=lambda x: (-x["points"], -(x["gf"] - x["ga"]), -x["gf"]))

# ================== ГЕНЕРАТОРЫ РАСПИСАНИЯ ==================
def generate_round_robin_fixtures(tid, teams_ids, date_iso, stadium=None, group_id=None):
    """Каждый с каждым в 2 круга. Возвращает список (home, away, date)."""
    if len(teams_ids) < 2:
        return []
    fixtures = []
    # первый круг
    for i in range(len(teams_ids)):
        for j in range(len(teams_ids)):
            if i != j:
                # чередуем дома/в гостях по формуле
                if (i + j) % 2 == 0:
                    fixtures.append((teams_ids[i], teams_ids[j], date_iso, stadium, group_id))
    # создаём в БД
    conn = get_connection()
    cur = conn.cursor()
    ids = []
    for h, a, d, s, gid in fixtures:
        cur.execute("""
            INSERT INTO matches (tournament_id, group_id, stage, home_team_id, away_team_id,
                                 date, stadium)
            VALUES (?,?, 'regular',?,?,?,?)""", (tid, gid, h, a, d, s))
        ids.append(cur.lastrowid)
    conn.commit()
    conn.close()
    return ids


def auto_distribute_groups(tid, num_groups):
    """Равномерно распределяет команды турнира по группам."""
    teams = get_tournament_teams(tid)
    if not teams:
        return []
    # удаляем старые группы
    delete_groups_for_tournament(tid)
    group_names = [chr(ord('A') + i) for i in range(num_groups)]
    group_ids = [create_group(tid, n) for n in group_names]
    # перемешиваем и раскладываем
    import random
    shuffled = list(teams)
    random.shuffle(shuffled)
    for i, t in enumerate(shuffled):
        gid = group_ids[i % num_groups]
        add_team_to_group(gid, t["id"])
    return group_ids