# F1 25 Real-Time Telemetry Coach

Your personal AI race engineer that helps you drive faster!

## 🎯 What This Does

Listens to F1 25 telemetry in real-time and provides audio coaching:
- "Brake now"
- "Downshift to 4th" 
- "Carry more speed"
- "Get on throttle"
- Live delta vs your best lap

## 📁 Files You Have

1. **telemetry_logger.py** - Records telemetry while you drive
2. **analyze_laps.py** - Finds your fastest lap and creates reference
3. **realtime_coach.py** - The real-time coach that speaks to you
4. **visualize_track.py** - Plots track maps
5. **reference_lap.csv** - Your fastest lap data (created by analyze_laps.py)

## 🚀 How to Use

### Step 1: Record Some Laps

```bash
python telemetry_logger.py
```

- Drive 3-5 laps in F1 25 Time Trial
- Press Ctrl+C when done
- Data saved to `logs/telemetry_TIMESTAMP.csv`

### Step 2: Find Your Fastest Lap

```bash
python analyze_laps.py
```

- Analyzes all your laps
- Identifies the fastest complete lap
- Creates `logs/reference_lap.csv` (this is your coaching reference)
- Shows comparison plots

### Step 3: Get Real-Time Coaching

```bash
python realtime_coach.py
```

- Loads your reference lap
- Starts listening for telemetry
- **Go drive in F1 25!**
- Listen to the audio coaching cues
- Watch the console for live delta and distance updates

### Step 4: Visualize Your Track

```bash
python visualize_track.py
```

- Shows track map colored by speed
- Shows direction arrows
- Displays track statistics

## ⚙️ F1 25 Settings

**CRITICAL - Set these in F1 25 Telemetry Settings:**

- UDP Telemetry: **ON**
- UDP Broadcast Mode: **ON**  
- UDP IP Address: **127.0.0.1**
- UDP Port: **20777**
- UDP Send Rate: **60Hz**
- UDP Format: **2025**
- Telemetry: **Public** (NOT Restricted)

## 🎮 Workflow

1. Record 3-5 laps → `telemetry_logger.py`
2. Analyze and find fastest → `analyze_laps.py`
3. Drive with live coaching → `realtime_coach.py`
4. Review your lines → `visualize_track.py`
5. Repeat to improve!

## 💡 Tips

- **Cooldowns:** Coach won't spam you - there's a 100m/2s cooldown between cues
- **Priority:** Coach focuses on the most impactful mistakes (braking, gears, speed)
- **Delta:** Positive = slower than reference, Negative = faster than reference
- **Best practice:** Record 5+ laps to get a solid reference lap

## 🐛 Troubleshooting

**No telemetry packets?**
- Check F1 25 telemetry settings (especially "Public" not "Restricted")
- Change UDP IP in script to `0.0.0.0` if `127.0.0.1` doesn't work
- Check Windows Firewall - allow Python

**Coach not speaking?**
- Make sure pyttsx3 is installed: `pip install pyttsx3`
- Check your audio output isn't muted
- TTS engine might need system dependencies (usually works on Windows)

**Lap distance stuck at 0?**
- Some F1 versions have lap distance issues
- Use position data instead (we can implement this if needed)

## 🔧 Requirements

```bash
pip install pandas matplotlib numpy pyttsx3
```

## 📊 Future Enhancements

- [ ] Visual dashboard with live track position
- [ ] Corner-by-corner analysis
- [ ] ML model for predictive coaching  
- [ ] Setup comparison (different car setups)
- [ ] Multi-lap strategy coaching

## 🏁 Have Fun!

Drive fast, listen to the coach, and improve your lap times!
