#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026 FIFA World Cup 实时赛况抓取 & ICS日历生成器
通过ESPN API自动抓取最新赛况，生成标准ICS日历文件
供GitHub Actions自动运行
"""

import requests
import json
import re
from datetime import datetime, timedelta
from icalendar import Calendar, Event, Alarm, vText
import pytz
import sys
import os

# ============================================================
# 配置
# ============================================================
ESPN_LEAGUE_CODE = "fifa.world"
ICS_OUTPUT_PATH = os.environ.get("ICS_OUTPUT", "worldcup-2026-calendar.ics")
HTML_OUTPUT_PATH = os.environ.get("HTML_OUTPUT", "index.html")
TIMEZONE_BEIJING = pytz.timezone("Asia/Shanghai")
TIMEZONE_UTC = pytz.UTC

# 比赛状态映射 (ESPN -> (英文状态, Emoji, 中文))
ESPN_STATUS_MAP = {
    "STATUS_SCHEDULED": ("Scheduled", "⏳", "未开始"),
    "STATUS_IN_PROGRESS": ("In Progress", "🔴", "进行中"),
    "STATUS_HALFTIME": ("Halftime", "🟡", "中场休息"),
    "STATUS_FINAL": ("Full Time", "✅", "已结束"),
    "STATUS_FULL_TIME": ("Full Time", "✅", "已结束"),
    "STATUS_POSTPONED": ("Postponed", "⏸️", "推迟"),
    "STATUS_CANCELLED": ("Cancelled", "❌", "取消"),
    "STATUS_DELAYED": ("Delayed", "⏱️", "延迟"),
    "STATUS_END_PERIOD": ("End of Period", "🟡", "阶段结束"),
    "STATUS_FIRST_HALF": ("First Half", "🔴", "上半场"),
    "STATUS_SECOND_HALF": ("Second Half", "🔴", "下半场"),
    "STATUS_EXTRA_TIME": ("Extra Time", "🔴", "加时赛"),
    "STATUS_FIRST_EXTRA": ("Extra Time", "🔴", "加时赛上半"),
    "STATUS_SECOND_EXTRA": ("Extra Time", "🔴", "加时赛下半"),
    "STATUS_PENALTY_SHOOTOUT": ("Penalty Shootout", "🔴", "点球大战"),
    "STATUS_ABANDONED": ("Abandoned", "❌", "取消"),
    "STATUS_SUSPENDED": ("Suspended", "⏸️", "暂停"),
    "STATUS_WALKOVER": ("Walkover", "✅", "弃权胜"),
}
# 已结束的状态集合
FINISHED_STATUSES = {"Full Time", "FINAL", "Walkover"}
# 进行中的状态集合
LIVE_STATUSES = {"In Progress", "Halftime", "First Half", "Second Half",
                 "Extra Time", "Penalty Shootout", "End of Period"}


def get_status_fallback(status_name, status_desc):
    """安全获取状态信息，避免未知状态名导致错误emoji"""
    if status_name in ESPN_STATUS_MAP:
        return ESPN_STATUS_MAP[status_name]
    # 根据描述智能判断
    desc_lower = status_desc.lower()
    if any(w in desc_lower for w in ["final", "full", "finished", "ended", "complete", "over"]):
        return (status_desc, "✅", "已结束")
    if any(w in desc_lower for w in ["progress", "live", "playing", "half", "extra", "penalty"]):
        return (status_desc, "🔴", "进行中")
    if any(w in desc_lower for w in ["delay", "suspend", "postpone"]):
        return (status_desc, "⏸️", "暂停")
    if any(w in desc_lower for w in ["cancel", "abandon"]):
        return (status_desc, "❌", "取消")
    # 默认：未开始
    return (status_desc, "⏳", "未开始")


# 中文队名映射（ESPN英文 -> 中文）
TEAM_NAME_MAP = {
    # Group A
    "Mexico": "墨西哥", "South Africa": "南非", "Korea Republic": "韩国",
    "Czechia": "捷克", "Czech Republic": "捷克",
    # Group B
    "Canada": "加拿大", "Bosnia and Herzegovina": "波黑",
    "Qatar": "卡塔尔", "Switzerland": "瑞士",
    # Group C
    "Brazil": "巴西", "Morocco": "摩洛哥", "Haiti": "海地", "Scotland": "苏格兰",
    # Group D
    "United States": "美国", "USA": "美国", "Paraguay": "巴拉圭",
    "Australia": "澳大利亚", "Turkiye": "土耳其", "Turkey": "土耳其",
    # Group E
    "Germany": "德国", "Curaçao": "库拉索", "Curacao": "库拉索",
    "Côte d'Ivoire": "科特迪瓦", "Ivory Coast": "科特迪瓦",
    "Ecuador": "厄瓜多尔",
    # Group F
    "Netherlands": "荷兰", "Japan": "日本", "Sweden": "瑞典", "Tunisia": "突尼斯",
    # Group G
    "Belgium": "比利时", "Egypt": "埃及", "IR Iran": "伊朗", "Iran": "伊朗",
    "New Zealand": "新西兰",
    # Group H
    "Spain": "西班牙", "Cabo Verde": "佛得角", "Cape Verde": "佛得角",
    "Saudi Arabia": "沙特阿拉伯",
    "Uruguay": "乌拉圭",
    # Group I
    "France": "法国", "Senegal": "塞内加尔", "Iraq": "伊拉克", "Norway": "挪威",
    # Group J
    "Argentina": "阿根廷", "Algeria": "阿尔及利亚", "Austria": "奥地利", "Jordan": "约旦",
    # Group K
    "Portugal": "葡萄牙", "Congo DR": "刚果（金）",
    "DR Congo": "刚果（金）", "Congo": "刚果（金）",
    "Uzbekistan": "乌兹别克斯坦", "Colombia": "哥伦比亚",
    # Group L
    "England": "英格兰", "Croatia": "克罗地亚", "Ghana": "加纳", "Panama": "巴拿马",
    # 淘汰赛占位
    "TBD": "待定", "TBD 1": "待定1", "TBD 2": "待定2",
    "TBD 3": "待定3", "TBD 4": "待定4",
}

# 场馆名称映射
VENUE_MAP = {
    "Estadio Azteca": "墨西哥城",
    "Estadio Akron": "瓜达拉哈拉",
    "Estadio BBVA": "蒙特雷",
    "Estadio Banorte": "墨西哥城",
    "SoFi Stadium": "洛杉矶",
    "Levi's Stadium": "旧金山湾区",
    "BMO Field": "多伦多",
    "BC Place": "温哥华",
    "MetLife Stadium": "纽约/新泽西",
    "Gillette Stadium": "波士顿",
    "Mercedes-Benz Stadium": "亚特兰大",
    "Hard Rock Stadium": "迈阿密",
    "NRG Stadium": "休斯顿",
    "AT&T Stadium": "达拉斯",
    "Lumen Field": "西雅图",
    "Lincoln Financial Field": "费城",
    "GEHA Field at Arrowhead Stadium": "堪萨斯城",
}


def translate_team(name):
    """将英文队名翻译为中文"""
    return TEAM_NAME_MAP.get(name, name)


def translate_venue(venue):
    """将英文场馆名翻译为中文"""
    if not venue:
        return "未知场馆"
    for en, zh in VENUE_MAP.items():
        if en.lower() in venue.lower():
            return zh
    return venue


def fetch_espn_scoreboard(date_str=None):
    """
    从ESPN API获取世界杯赛况数据
    date_str: YYYYMMDD格式，如 "20260620"
    """
    url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{ESPN_LEAGUE_CODE}/scoreboard"
    if date_str:
        url += f"?dates={date_str}"

    try:
        resp = requests.get(url, timeout=30)
        if resp.status_code == 200:
            return resp.json()
        else:
            print(f"  ESPN API返回状态码: {resp.status_code}")
            return None
    except Exception as e:
        print(f"  ESPN API请求失败: {e}")
        return None


def fetch_all_matches():
    """
    获取世界杯所有比赛数据
    从开幕日到决赛日逐日查询
    """
    all_matches = []

    # 世界杯日期范围 (北京时间)
    start_date = datetime(2026, 6, 11)
    end_date = datetime(2026, 7, 20)

    current = start_date
    while current <= end_date:
        date_str = current.strftime("%Y%m%d")
        print(f"  抓取 {date_str} 的赛况...")
        data = fetch_espn_scoreboard(date_str)

        if data and "events" in data:
            for event in data["events"]:
                match = parse_espn_event(event)
                if match:
                    all_matches.append(match)

        current += timedelta(days=1)

    return all_matches


def parse_espn_event(event):
    """解析ESPN单场比赛数据"""
    try:
        event_id = event.get("id", "")
        name = event.get("name", "")

        # 解析比赛状态
        status_obj = event.get("status", {})
        status_type = status_obj.get("type", {})
        status_name = status_type.get("name", "STATUS_SCHEDULED")
        status_desc = status_type.get("description", "")

        status_info = get_status_fallback(status_name, status_desc)

        # 解析比赛信息
        competitions = event.get("competitions", [])
        if not competitions:
            return None

        comp = competitions[0]
        competitors = comp.get("competitors", [])

        home_team = None
        away_team = None
        home_score = None
        away_score = None
        home_id = None
        away_id = None

        for c in competitors:
            team_name = c.get("team", {}).get("displayName", "Unknown")
            score = c.get("score", "")
            home_away = c.get("homeAway", "")
            team_id = c.get("team", {}).get("id", "")

            if home_away == "home":
                home_team = translate_team(team_name)
                home_score = score if score and score != "" else None
                home_id = team_id
            elif home_away == "away":
                away_team = translate_team(team_name)
                away_score = score if score and score != "" else None
                away_id = team_id

        if not home_team or not away_team:
            return None

        # 解析比赛时间
        start_time = None
        date_obj = comp.get("date")
        if date_obj:
            try:
                dt = datetime.fromisoformat(date_obj.replace("Z", "+00:00"))
                start_time = dt.astimezone(TIMEZONE_BEIJING)
            except:
                pass

        # 解析场馆
        venue = comp.get("venue", {})
        venue_name = translate_venue(venue.get("fullName", ""))

        # 解析小组信息
        group_name = ""
        for c in competitions:
            if c.get("group"):
                group_name = c["group"].get("name", "")
                break

        # ========== 解析进球事件（增强版） ==========
        goals = []
        details = comp.get("details", [])

        # 构建队名ID查找表
        team_id_to_side = {}
        for c in competitors:
            tid = c.get("team", {}).get("id", "")
            side = c.get("homeAway", "")
            if tid:
                team_id_to_side[tid] = side

        for detail in details:
            event_type = detail.get("type", {})
            is_goal_event = (
                event_type.get("id") == "70" or
                event_type.get("text") == "Goal" or
                event_type.get("description") == "Goal" or
                event_type.get("text") == "Goal (Penalty)" or
                event_type.get("text") == "Goal (Own)" or
                event_type.get("description") == "Goal (Penalty)" or
                event_type.get("description") == "Goal (Own)"
            )
            if not is_goal_event:
                continue

            clock = detail.get("clock", {})
            time_display = clock.get("displayValue", "")

            # 判断进球属于哪队
            team_id = detail.get("team", {}).get("id", "")
            team_side = team_id_to_side.get(team_id, "home")

            # 判读是否为主队进球（用于显示队名）
            team_name_display = home_team if team_side == "home" else away_team

            # 判断进球类型
            goal_type = ""
            if detail.get("penaltyKick"):
                goal_type = "（点球）"
            elif detail.get("ownGoal"):
                goal_type = "（乌龙）"
            elif detail.get("shootout"):
                goal_type = "（点球大战）"

            # 获取助攻球员（如果有第二个athletesInvolved，通常是助攻者）
            athletes = detail.get("athletesInvolved", [])
            scorer = athletes[0] if len(athletes) > 0 else {}
            assister = athletes[1] if len(athletes) > 1 else {}

            player_name = scorer.get("displayName", "未知球员")
            player_short = scorer.get("shortName", player_name)
            player_jersey = scorer.get("jersey", "")
            player_position = scorer.get("position", "")

            # 助攻信息
            assist_name = assister.get("displayName", "") if assister else ""

            # 根据scoringPlay排除非得分事件
            scoring_play = detail.get("scoringPlay", True)

            if scoring_play or detail.get("ownGoal"):
                goals.append({
                    "time": time_display,
                    "player": player_name,
                    "player_short": player_short,
                    "jersey": player_jersey,
                    "position": player_position,
                    "team_id": team_id,
                    "team_side": team_side,
                    "team": team_name_display,
                    "type": goal_type,
                    "assist": assist_name,
                    "penalty": detail.get("penaltyKick", False),
                    "own_goal": detail.get("ownGoal", False),
                })

        # 比分显示
        if home_score is not None and away_score is not None:
            score_display = f"{home_score}-{away_score}"
        else:
            score_display = "-"

        return {
            "match_id": f"fifa-2026-{event_id}",
            "home": home_team,
            "away": away_team,
            "home_score": home_score,
            "away_score": away_score,
            "score": score_display,
            "status": status_info[0],
            "status_emoji": status_info[1],
            "status_cn": status_info[2],
            "start_time": start_time,
            "venue": venue_name,
            "group": group_name,
            "espn_id": event_id,
            "goals": goals,
        }
    except Exception as e:
        print(f"  解析比赛数据失败: {e}")
        return None


def refetch_finished_matches(matches):
    """
    重新拉取已结束比赛以补全进球数据
    因为比赛进行中时ESPN API可能还没填充details
    """
    now = datetime.now(TIMEZONE_BEIJING)
    refetched = 0
    fixed = 0

    for match in matches:
        # 只处理已结束但无进球数据的比赛
        if match["status"] not in FINISHED_STATUSES:
            continue
        if not match.get("espn_id"):
            continue

        # 如果有进球数据且进球数合理，跳过
        if len(match.get("goals", [])) > 0:
            continue

        espn_id = match["espn_id"]
        print(f"  重新拉取已完成比赛 {match['home']} vs {match['away']} (ID: {espn_id})...")

        # 使用summary API获取单场比赛详情（包含完整细节）
        try:
            url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{ESPN_LEAGUE_CODE}/summary?event={espn_id}"
            resp = requests.get(url, timeout=30)
            if resp.status_code != 200:
                continue

            data = resp.json()
            events = data.get("events", [])
            if not events:
                continue

            event = events[0]
            competitions = event.get("competitions", [])
            if not competitions:
                continue

            comp = competitions[0]
            details = comp.get("details", [])

            if not details:
                continue

            refetched += 1

            # 解析进球
            competitors = comp.get("competitors", [])
            team_id_to_side = {}
            for c in competitors:
                tid = c.get("team", {}).get("id", "")
                side = c.get("homeAway", "")
                if tid:
                    team_id_to_side[tid] = side

            home_team_name = match["home"]
            away_team_name = match["away"]

            goals = []
            for detail in details:
                event_type = detail.get("type", {})
                is_goal = (
                    event_type.get("id") == "70" or
                    "Goal" in (event_type.get("text") or "") or
                    "Goal" in (event_type.get("description") or "")
                )
                if not is_goal:
                    continue

                clock = detail.get("clock", {})
                time_display = clock.get("displayValue", "")

                team_id = detail.get("team", {}).get("id", "")
                team_side = team_id_to_side.get(team_id, "home")
                team_name_display = home_team_name if team_side == "home" else away_team_name

                goal_type = ""
                if detail.get("penaltyKick"):
                    goal_type = "（点球）"
                elif detail.get("ownGoal"):
                    goal_type = "（乌龙）"
                elif detail.get("shootout"):
                    goal_type = "（点球大战）"

                athletes = detail.get("athletesInvolved", [])
                scorer = athletes[0] if len(athletes) > 0 else {}
                assister = athletes[1] if len(athletes) > 1 else {}

                player_name = scorer.get("displayName", "未知球员")
                player_short = scorer.get("shortName", player_name)
                player_jersey = scorer.get("jersey", "")
                player_position = scorer.get("position", "")
                assist_name = assister.get("displayName", "") if assister else ""
                scoring_play = detail.get("scoringPlay", True)

                if scoring_play or detail.get("ownGoal"):
                    goals.append({
                        "time": time_display,
                        "player": player_name,
                        "player_short": player_short,
                        "jersey": player_jersey,
                        "position": player_position,
                        "team_id": team_id,
                        "team_side": team_side,
                        "team": team_name_display,
                        "type": goal_type,
                        "assist": assist_name,
                        "penalty": detail.get("penaltyKick", False),
                        "own_goal": detail.get("ownGoal", False),
                    })

            if goals:
                match["goals"] = goals
                fixed += 1
                print(f"    -> 补全 {len(goals)} 个进球记录")

        except Exception as e:
            print(f"    -> 重新拉取失败: {e}")
            continue

    print(f"  重新拉取 {refetched} 场，补全 {fixed} 场的进球数据")
    return matches


def format_goal_line(goal):
    """格式化单条进球信息为易读文本"""
    parts = []

    # 进球时间
    parts.append(f"进球时间 {goal['time']}")

    # 球员信息：球衣号 + 姓名
    player = goal.get("player", "")
    jersey = goal.get("jersey", "")
    if jersey and player:
        parts.append(f"{jersey}号球员 {player}")
    elif player:
        parts.append(f"球员 {player}")

    # 场上位置（展开缩写为中文）
    position = goal.get("position", "")
    if position:
        pos_map = {
            "GK": "门将", "CD": "中后卫", "CD-L": "左中卫", "CD-R": "右中卫",
            "LB": "左后卫", "RB": "右后卫", "LWB": "左翼卫", "RWB": "右翼卫",
            "DM": "后腰", "DM-L": "左后腰", "DM-R": "右后腰",
            "CM": "中前卫", "CM-L": "左中前卫", "CM-R": "右中前卫",
            "LM": "左前卫", "RM": "右前卫",
            "AM": "前腰", "AM-L": "左前腰", "AM-R": "右前腰",
            "LW": "左边锋", "RW": "右边锋",
            "F": "前锋", "CF": "中锋", "CF-L": "左中锋", "CF-R": "右中锋",
            "SS": "影锋", "SUB": "替补",
        }
        pos_cn = pos_map.get(position, position)
        parts.append(f"位置：{pos_cn}")

    # 进球类型
    gtype = goal.get("type", "")
    if gtype:
        parts.append(gtype)

    # 助攻
    assist = goal.get("assist", "")
    if assist:
        parts.append(f"助攻：{assist}")

    return "，".join(parts)


def generate_ics(matches):
    """生成ICS日历文件"""
    cal = Calendar()
    cal.add("prodid", "-//World Cup 2026 Calendar//Auto Results//ZH")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("method", "PUBLISH")
    cal.add("x-wr-calname", "2026 世界杯")
    cal.add("x-wr-caldesc", "2026 FIFA 世界杯赛程与赛果（自动更新）")
    cal.add("x-published-ttl", "PT1H")
    cal.add("refresh-interval;value=duration", "PT1H")

    now = datetime.now(TIMEZONE_UTC)

    for match in matches:
        if not match.get("start_time"):
            continue

        event = Event()

        dt_start = match["start_time"].astimezone(TIMEZONE_UTC)
        dt_end = dt_start + timedelta(hours=2, minutes=45)

        # 标题
        emoji = match["status_emoji"]
        if match["status"] in FINISHED_STATUSES:
            summary = f"{emoji} {match['home']} {match['score']} {match['away']}"
        elif match["status"] in LIVE_STATUSES:
            summary = f"{emoji} {match['home']} {match['score']} {match['away']} ({match['status_cn']})"
        else:
            summary = f"{emoji} {match['home']} vs {match['away']}"

        # 描述
        beijing_time = match["start_time"].strftime("%Y-%m-%d %H:%M")
        desc_lines = [
            f"赛事：2026 FIFA世界杯",
            f"状态：{match['status_cn']}",
            f"开球：{beijing_time} UTC+8",
            f"场馆：{match['venue']}",
        ]
        if match["group"]:
            desc_lines.append(f"小组：{match['group']}")
        if match["score"] != "-":
            desc_lines.append(f"赛果：{match['home']} {match['score']} {match['away']}")

        # 添加进球球员信息（增强版）
        if match.get("goals"):
            desc_lines.append("")
            desc_lines.append("⚽ 进球记录：")
            for goal in match["goals"]:
                team_side = goal.get("team_side", "")
                team_mark = f" [{match['home']}]" if team_side == "home" else f" [{match['away']}]"
                goal_line = f"  {format_goal_line(goal)}{team_mark}"
                desc_lines.append(goal_line)

        desc_lines.append("")
        desc_lines.append(f"ESPN：https://www.espn.com/soccer/match/_/gameId/{match['espn_id']}")
        desc_lines.append(f"自动更新，数据来源为ESPN公开数据")

        description = "\n".join(desc_lines)

        event.add("uid", f"{match['match_id']}@worldcup-calendar")
        event.add("dtstamp", now)
        event.add("created", now)
        event.add("last-modified", now)
        event.add("dtstart", dt_start)
        event.add("dtend", dt_end)
        event.add("summary", summary)
        event.add("description", description)
        event.add("location", vText(match["venue"]))
        event.add("status", "CONFIRMED")
        event.add("transp", "OPAQUE")
        event.add("class", "PUBLIC")

        # 比赛开始前30分钟静默提醒（无提示音）
        alarm = Alarm()
        alarm.add("action", "DISPLAY")
        alarm.add("description", f"比赛即将开始：{match['home']} vs {match['away']}")
        alarm.add("trigger", timedelta(minutes=-30))
        # 静音设置：Apple日历、Google日历、Outlook均不播放提示音
        alarm.add("X-APPLE-CALENDAR-SOUND", "None")
        alarm.add("X-WR-ALARMUID", f"alarm-{match['espn_id']}")
        event.add_component(alarm)

        cal.add_component(event)

    return cal


def save_ics(cal, filepath):
    """保存ICS文件"""
    os.makedirs(os.path.dirname(filepath) if os.path.dirname(filepath) else ".", exist_ok=True)
    with open(filepath, "wb") as f:
        f.write(cal.to_ical())
    print(f"  ICS文件已保存: {filepath} ({len(cal.subcomponents)} 场比赛)")


def generate_html(matches):
    """生成HTML订阅页面"""
    now = datetime.now(TIMEZONE_BEIJING)

    # 按日期排序，取最近的比赛
    sorted_matches = sorted(
        [m for m in matches if m.get("start_time")],
        key=lambda x: x["start_time"]
    )

    # 近期比赛（前后3天）
    recent = []
    for m in sorted_matches:
        dt = m["start_time"]
        if (dt - timedelta(hours=12)) <= now <= (dt + timedelta(days=3)):
            recent.append(m)
    recent = recent[:15]

    # 统计
    total = len(matches)
    finished = sum(1 for m in matches if m["status"] in FINISHED_STATUSES)
    in_progress = sum(1 for m in matches if m["status"] in LIVE_STATUSES)
    scheduled = total - finished - in_progress

    # 生成比赛列表HTML
    matches_html = ""
    for m in recent:
        beijing_time = m["start_time"].strftime("%Y-%m-%d %H:%M")
        group_info = f" | {m['group']}" if m["group"] else ""

        if m["status"] in FINISHED_STATUSES:
            status_class = "status-finished"
            status_text = "已结束"
            teams = f"{m['home']} {m['score']} {m['away']}"
        elif m["status"] in LIVE_STATUSES:
            status_class = "status-live"
            status_text = m["status_cn"]
            teams = f"{m['home']} {m['score']} {m['away']}"
        else:
            status_class = "status-scheduled"
            status_text = "未开始"
            teams = f"{m['home']} vs {m['away']}"

        # 进球球员信息（增强版）
        goals_html = ""
        if m.get("goals"):
            home_goals = [g for g in m["goals"] if g.get("team_side") == "home"]
            away_goals = [g for g in m["goals"] if g.get("team_side") == "away"]
            goal_lines = []

            for g_label, g_list in [("🏠", home_goals), ("✈", away_goals)]:
                for goal in g_list:
                    g = f"{goal['time']}"
                    if goal.get("jersey"):
                        g += f" #{goal['jersey']}"
                    g += f" {goal['player']}"
                    if goal.get("type"):
                        g += f" {goal['type']}"
                    if goal.get("assist"):
                        g += f"（{goal['assist']}）"
                    goal_lines.append(g)

            if goal_lines:
                goals_html = f'<div style="color: #a0a0a0; font-size: 0.8rem; margin-top: 4px;">⚽ {" · ".join(goal_lines)}</div>'

        matches_html += f"""
                <div class="match-item">
                    <div class="match-teams">
                        <strong>{teams}</strong>
                        <div class="match-time">{beijing_time} | {m['venue']}{group_info}</div>
                        {goals_html}
                    </div>
                    <span class="match-status {status_class}">{status_text}</span>
                </div>
"""

    # 更新时间
    update_time = now.strftime("%Y-%m-%d %H:%M:%S UTC+8")

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>2026世界杯日历订阅服务</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
            min-height: 100vh; color: #fff; padding: 20px;
        }}
        .container {{ max-width: 800px; margin: 0 auto; }}
        .header {{ text-align: center; padding: 40px 0; }}
        .header h1 {{
            font-size: 2.5rem; margin-bottom: 10px;
            background: linear-gradient(90deg, #e94560, #ff6b6b);
            -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
        }}
        .header p {{ color: #a0a0a0; font-size: 1.1rem; }}
        .card {{
            background: rgba(255, 255, 255, 0.05); border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 16px; padding: 30px; margin-bottom: 20px; backdrop-filter: blur(10px);
        }}
        .card h2 {{ font-size: 1.5rem; margin-bottom: 20px; color: #e94560; }}
        .subscription-link {{
            background: rgba(233, 69, 96, 0.1); border: 2px dashed #e94560;
            border-radius: 12px; padding: 20px; text-align: center; margin: 20px 0;
            word-break: break-all;
        }}
        .subscription-link code {{
            font-family: 'Courier New', monospace; font-size: 0.85rem; color: #e94560;
        }}
        .link-label {{ font-size: 0.8rem; color: #a0a0a0; margin-bottom: 8px; }}
        .btn {{
            display: inline-block; background: linear-gradient(90deg, #e94560, #ff6b6b);
            color: #fff; padding: 12px 30px; border-radius: 25px; text-decoration: none;
            font-weight: 600; margin: 10px 5px; transition: transform 0.3s, box-shadow 0.3s;
            border: none; cursor: pointer;
        }}
        .btn:hover {{ transform: translateY(-2px); box-shadow: 0 10px 20px rgba(233, 69, 96, 0.3); }}
        .btn-secondary {{
            background: linear-gradient(90deg, #0f3460, #16213e);
            border: 1px solid rgba(255, 255, 255, 0.2);
        }}
        .steps {{ list-style: none; counter-reset: step; }}
        .steps li {{
            position: relative; padding-left: 50px; margin-bottom: 20px; line-height: 1.6;
        }}
        .steps li::before {{
            counter-increment: step; content: counter(step); position: absolute; left: 0; top: 0;
            width: 35px; height: 35px; background: linear-gradient(135deg, #e94560, #ff6b6b);
            border-radius: 50%; display: flex; align-items: center; justify-content: center;
            font-weight: bold; font-size: 0.9rem;
        }}
        .match-list {{ max-height: 500px; overflow-y: auto; }}
        .match-item {{
            display: flex; justify-content: space-between; align-items: center;
            padding: 12px; border-bottom: 1px solid rgba(255, 255, 255, 0.05);
            transition: background 0.3s;
        }}
        .match-item:hover {{ background: rgba(255, 255, 255, 0.05); border-radius: 8px; }}
        .match-teams {{ flex: 1; }}
        .match-time {{ color: #a0a0a0; font-size: 0.85rem; }}
        .match-status {{
            padding: 4px 12px; border-radius: 12px; font-size: 0.8rem; font-weight: 600;
        }}
        .status-finished {{ background: rgba(46, 204, 113, 0.2); color: #2ecc71; }}
        .status-scheduled {{ background: rgba(241, 196, 15, 0.2); color: #f1c40f; }}
        .status-live {{ background: rgba(231, 76, 60, 0.2); color: #e74c3c; animation: pulse 2s infinite; }}
        @keyframes pulse {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0.5; }} }}
        .footer {{ text-align: center; padding: 40px 0; color: #666; font-size: 0.9rem; }}
        .platform-tabs {{ display: flex; gap: 10px; margin-bottom: 20px; }}
        .platform-tab {{
            flex: 1; padding: 10px; text-align: center;
            background: rgba(255, 255, 255, 0.05); border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 8px; cursor: pointer; transition: all 0.3s;
        }}
        .platform-tab.active {{ background: rgba(233, 69, 96, 0.2); border-color: #e94560; }}
        .platform-content {{ display: none; }}
        .platform-content.active {{ display: block; }}
        .mirror-badge {{
            display: inline-block; background: rgba(52, 152, 219, 0.2); color: #3498db;
            padding: 2px 8px; border-radius: 4px; font-size: 0.7rem; margin-left: 8px;
        }}
        .stats {{ display: flex; gap: 15px; justify-content: center; margin: 15px 0; }}
        .stat-item {{
            text-align: center; padding: 10px 20px;
            background: rgba(255, 255, 255, 0.05); border-radius: 10px;
        }}
        .stat-num {{ font-size: 1.5rem; font-weight: bold; color: #e94560; }}
        .stat-label {{ font-size: 0.75rem; color: #a0a0a0; margin-top: 4px; }}
        .update-info {{
            text-align: center; font-size: 0.8rem; color: #666;
            padding: 10px; background: rgba(255,255,255,0.03); border-radius: 8px; margin-top: 15px;
        }}
        @media (max-width: 600px) {{
            .header h1 {{ font-size: 1.8rem; }}
            .card {{ padding: 20px; }}
            .subscription-link code {{ font-size: 0.75rem; }}
            .stats {{ flex-wrap: wrap; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🏆 2026世界杯日历订阅</h1>
            <p>实时赛况自动更新 · 进球球员详情 · 手机日历同步</p>
        </div>

        <div class="card">
            <h2>📊 赛事统计</h2>
            <div class="stats">
                <div class="stat-item">
                    <div class="stat-num">{total}</div>
                    <div class="stat-label">总场次</div>
                </div>
                <div class="stat-item">
                    <div class="stat-num">{finished}</div>
                    <div class="stat-label">已结束</div>
                </div>
                <div class="stat-item">
                    <div class="stat-num">{in_progress}</div>
                    <div class="stat-label">进行中</div>
                </div>
                <div class="stat-item">
                    <div class="stat-num">{scheduled}</div>
                    <div class="stat-label">未开始</div>
                </div>
            </div>
            <div class="update-info">
                🕐 数据更新时间：{update_time}（每30分钟自动抓取ESPN数据）
            </div>
        </div>

        <div class="card">
            <h2>📱 订阅链接</h2>
            <p>复制以下链接，按照下方教程导入到您的手机日历：</p>

            <div class="subscription-link">
                <div class="link-label">🌐 订阅链接 <span class="mirror-badge">GitHub Pages</span></div>
                <code id="subscription-url">https://Fake-msn.github.io/worldcup-2026-calendar/worldcup-2026-calendar.ics</code>
            </div>

            <div style="text-align: center;">
                <button class="btn" onclick="copyLink()">📋 复制订阅链接</button>
                <a href="worldcup-2026-calendar.ics" class="btn" download>📥 下载ICS文件</a>
            </div>

            <div style="margin-top: 20px; padding: 15px; background: rgba(241, 196, 15, 0.1); border-left: 4px solid #f1c40f; border-radius: 8px;">
                <p style="font-size: 0.9rem; color: #f1c40f; margin-bottom: 8px;">⚠️ 国内用户注意</p>
                <p style="font-size: 0.85rem; color: #a0a0a0;">
                    GitHub Pages在国内部分地区可能访问不稳定。如果遇到无法订阅的情况，请使用以下方法：
                </p>
                <ol style="font-size: 0.85rem; color: #a0a0a0; margin-top: 10px; padding-left: 20px; line-height: 1.8;">
                    <li>点击上方"下载ICS文件"按钮，将文件保存到手机</li>
                    <li>打开手机的日历应用</li>
                    <li>选择"导入日历"或"添加日历文件"</li>
                    <li>选择刚才下载的ICS文件导入</li>
                </ol>
                <p style="font-size: 0.85rem; color: #a0a0a0; margin-top: 10px;">
                    📌 文件导入后不会自动更新，建议比赛日前重新下载最新版本。
                </p>
            </div>
        </div>

        <div class="card">
            <h2>📖 导入教程</h2>
            <div class="platform-tabs">
                <div class="platform-tab active" onclick="showPlatform('ios')">iPhone</div>
                <div class="platform-tab" onclick="showPlatform('android')">Android</div>
                <div class="platform-tab" onclick="showPlatform('google')">Google日历</div>
            </div>

            <div id="ios" class="platform-content active">
                <ol class="steps">
                    <li>打开<strong>设置</strong> → <strong>日历</strong> → <strong>账户</strong></li>
                    <li>点击<strong>添加账户</strong> → 选择<strong>其他</strong></li>
                    <li>选择<strong>添加已订阅的日历</strong></li>
                    <li>粘贴上面的订阅链接，点击<strong>下一步</strong></li>
                    <li>完成订阅，打开日历App即可查看</li>
                </ol>
                <p style="color: #a0a0a0; font-size: 0.9rem; margin-top: 10px;">
                    📌 快捷方式：直接在Safari中打开订阅链接，系统会自动提示添加日历。
                </p>
            </div>

            <div id="android" class="platform-content">
                <ol class="steps">
                    <li>打开<strong>Google日历</strong>应用</li>
                    <li>点击左上角<strong>☰ 菜单</strong> → <strong>设置</strong></li>
                    <li>选择<strong>添加日历</strong> → <strong>从URL添加</strong></li>
                    <li>粘贴订阅链接，点击<strong>确定</strong></li>
                    <li>日历将自动同步到您的设备</li>
                </ol>
            </div>

            <div id="google" class="platform-content">
                <ol class="steps">
                    <li>访问 <strong>calendar.google.com</strong></li>
                    <li>左侧点击<strong>+ 其他日历</strong> → <strong>通过链接添加</strong></li>
                    <li>粘贴订阅链接，点击<strong>添加日历</strong></li>
                    <li>日历将出现在您的Google日历列表中</li>
                </ol>
            </div>
        </div>

        <div class="card">
            <h2>📅 近期赛程</h2>
            <div class="match-list">
                {matches_html}
            </div>
        </div>

        <div class="card">
            <h2>⚙️ 技术说明</h2>
            <p><strong>数据来源：</strong>ESPN足球数据API（实时比分）</p>
            <p><strong>更新频率：</strong>每30分钟自动抓取（GitHub Actions）</p>
            <p><strong>数据格式：</strong>标准ICS日历格式 (RFC 5545)</p>
            <p><strong>支持平台：</strong>iOS日历、Google日历、Outlook、小米日历等</p>
            <p><strong>提醒设置：</strong>比赛开始前30分钟自动提醒</p>
            <p><strong>进球信息：</strong>已结束比赛自动补全进球球员、球衣号、助攻信息</p>
        </div>

        <div class="footer">
            <p>2026 FIFA World Cup Calendar Subscription Service</p>
            <p style="margin-top: 10px; font-size: 0.8rem;">数据仅供参考，请以FIFA官方公布为准</p>
        </div>
    </div>

    <script>
        function copyLink() {{
            const url = document.getElementById('subscription-url').textContent;
            navigator.clipboard.writeText(url).then(() => {{
                alert('订阅链接已复制到剪贴板！');
            }});
        }}

        function showPlatform(platform) {{
            document.querySelectorAll('.platform-tab').forEach(tab => tab.classList.remove('active'));
            document.querySelectorAll('.platform-content').forEach(content => content.classList.remove('active'));
            event.target.classList.add('active');
            document.getElementById(platform).classList.add('active');
        }}
    </script>
</body>
</html>"""

    filepath = HTML_OUTPUT_PATH
    os.makedirs(os.path.dirname(filepath) if os.path.dirname(filepath) else ".", exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  HTML页面已保存: {filepath}")


# 世界杯结束后自动停止抓取的截止日期（决赛后一周）
CUTOFF_DATE = TIMEZONE_BEIJING.localize(datetime(2026, 7, 26, 23, 59, 59))


def main():
    print("=" * 60)
    print("2026 FIFA World Cup 实时赛况抓取器")
    print(f"运行时间: {datetime.now(TIMEZONE_BEIJING).strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # 检查是否已过截止日期
    now = datetime.now(TIMEZONE_BEIJING)
    if now > CUTOFF_DATE:
        print(f"\n世界杯已结束（截止日期: {CUTOFF_DATE.strftime('%Y-%m-%d')}），停止自动更新。")
        print("如需重新启用，请修改脚本中的 CUTOFF_DATE 变量。")
        sys.exit(0)

    # 1. 抓取所有比赛数据
    print("\n[1/4] 从ESPN API抓取赛况数据...")
    matches = fetch_all_matches()
    print(f"  共获取 {len(matches)} 场比赛")

    if not matches:
        print("  未获取到任何比赛数据，退出")
        sys.exit(1)

    # 统计
    finished = sum(1 for m in matches if m["status"] in FINISHED_STATUSES)
    in_progress = sum(1 for m in matches if m["status"] in LIVE_STATUSES)
    scheduled = len(matches) - finished - in_progress
    print(f"  已结束: {finished} | 进行中: {in_progress} | 未开始: {scheduled}")

    # 2. 重新拉取已结束比赛补全进球数据
    print("\n[2/4] 重新拉取已结束比赛补全进球数据...")
    matches = refetch_finished_matches(matches)

    # 统计进球数据覆盖情况
    matches_with_goals = sum(1 for m in matches if m.get("goals") and len(m["goals"]) > 0)
    total_goals = sum(len(m.get("goals", [])) for m in matches)
    print(f"  有进球记录的场次: {matches_with_goals}，总进球数: {total_goals}")

    # 3. 生成ICS文件
    print("\n[3/4] 生成ICS日历文件...")
    cal = generate_ics(matches)
    save_ics(cal, ICS_OUTPUT_PATH)

    # 4. 生成HTML页面
    print("\n[4/4] 生成HTML订阅页面...")
    generate_html(matches)

    print(f"\n{'='*60}")
    print("全部完成!")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()