import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import os
import sys

def analyze_laps(csv_file):
    """Analyze individual laps and identify the fastest complete lap."""

    print(f"Loading {csv_file}...")
    df = pd.read_csv(csv_file)
    print(f"Loaded {len(df)} telemetry points\n")

    # Get unique laps, skip formation (lap 0 and below)
    all_laps = sorted(df['current_lap_num'].unique())
    racing_laps = [l for l in all_laps if l >= 1]

    if not racing_laps:
        print("No racing laps found!")
        return None

    print("=" * 70)
    print("LAP ANALYSIS")
    print("=" * 70)

    lap_info = []

    for lap_num in racing_laps:
        lap_df = df[df['current_lap_num'] == lap_num]

        # Get the actual lap time from the NEXT lap's last_lap_time field
        # (last_lap_time updates when crossing the line, so it appears on the next lap's data)
        next_lap_df = df[df['current_lap_num'] == lap_num + 1]
        if len(next_lap_df) > 0:
            lap_time = next_lap_df['last_lap_time'].iloc[0]
            is_complete = lap_time > 0
        else:
            # No next lap data = this lap wasn't completed (or session ended)
            # Use current_lap_time as estimate
            lap_time = lap_df['current_lap_time'].max() if len(lap_df) > 0 else 0
            is_complete = False

        max_speed = lap_df['speed'].max()
        avg_speed = lap_df['speed'].mean()

        lap_info.append({
            'lap_num': lap_num,
            'points': len(lap_df),
            'lap_time': lap_time,
            'max_speed': max_speed,
            'avg_speed': avg_speed,
            'is_complete': is_complete
        })

        status = "COMPLETE" if is_complete else "INCOMPLETE"
        print(f"Lap {lap_num:2d} | {lap_time:7.3f}s | {len(lap_df):5d} pts | "
              f"Max: {max_speed:3.0f} km/h | Avg: {avg_speed:3.0f} km/h | {status}")

    # Find fastest complete lap
    complete_laps = [l for l in lap_info if l['is_complete']]

    if not complete_laps:
        print("\nNo complete laps found! Complete at least 2 laps to get timing data.")
        return None

    fastest_lap = min(complete_laps, key=lambda x: x['lap_time'])

    print("\n" + "=" * 70)
    print(f"FASTEST COMPLETE LAP: Lap {fastest_lap['lap_num']} - {fastest_lap['lap_time']:.3f}s")
    print("=" * 70)

    # Create reference lap data
    reference_df = df[df['current_lap_num'] == fastest_lap['lap_num']].copy()
    reference_df = reference_df.sort_values('lap_distance').reset_index(drop=True)

    # Save reference lap
    output_dir = os.path.dirname(csv_file)
    reference_file = os.path.join(output_dir, 'reference_lap.csv')
    reference_df.to_csv(reference_file, index=False)
    print(f"\nReference lap saved to: {reference_file}")

    # Plot all laps comparison
    plot_laps_comparison(df, lap_info, fastest_lap['lap_num'], csv_file)

    return reference_df, fastest_lap

def plot_laps_comparison(df, lap_info, fastest_lap_num, csv_file):
    """Plot comparison of all laps."""

    fig, axes = plt.subplots(2, 2, figsize=(16, 12))

    # Color palette
    colors = plt.cm.tab10(np.linspace(0, 1, 10))

    # Plot 1: Track maps of all laps
    ax1 = axes[0, 0]
    for i, lap in enumerate(lap_info):
        lap_num = lap['lap_num']
        lap_df = df[df['current_lap_num'] == lap_num]

        if lap['is_complete']:
            linewidth = 2.5 if lap_num == fastest_lap_num else 1.5
            alpha = 1.0 if lap_num == fastest_lap_num else 0.6
            label = f"Lap {lap_num} ({lap['lap_time']:.3f}s)" + (" *" if lap_num == fastest_lap_num else "")
            ax1.plot(lap_df['pos_x'], lap_df['pos_z'],
                    color=colors[i % 10], linewidth=linewidth, alpha=alpha, label=label)

    ax1.set_xlabel('X Position (m)', fontsize=12)
    ax1.set_ylabel('Z Position (m)', fontsize=12)
    ax1.set_title('All Laps - Track Comparison', fontsize=14, fontweight='bold')
    ax1.legend(loc='best', fontsize=10)
    ax1.grid(True, alpha=0.3)
    ax1.set_aspect('equal')

    # Plot 2: Speed vs Distance for all laps
    ax2 = axes[0, 1]
    for i, lap in enumerate(lap_info):
        lap_num = lap['lap_num']
        lap_df = df[df['current_lap_num'] == lap_num]

        if lap['is_complete']:
            linewidth = 2.5 if lap_num == fastest_lap_num else 1.5
            alpha = 1.0 if lap_num == fastest_lap_num else 0.6
            ax2.plot(lap_df['lap_distance'], lap_df['speed'],
                    color=colors[i % 10], linewidth=linewidth, alpha=alpha)

    ax2.set_xlabel('Lap Distance (m)', fontsize=12)
    ax2.set_ylabel('Speed (km/h)', fontsize=12)
    ax2.set_title('Speed Trace - All Laps', fontsize=14, fontweight='bold')
    ax2.grid(True, alpha=0.3)

    # Plot 3: Throttle/Brake comparison for fastest lap
    ax3 = axes[1, 0]
    fastest_df = df[df['current_lap_num'] == fastest_lap_num]
    ax3.plot(fastest_df['lap_distance'], fastest_df['throttle'],
            'g-', linewidth=1.5, label='Throttle', alpha=0.8)
    ax3.plot(fastest_df['lap_distance'], fastest_df['brake'],
            'r-', linewidth=1.5, label='Brake', alpha=0.8)
    ax3.fill_between(fastest_df['lap_distance'], 0, fastest_df['throttle'],
                     color='green', alpha=0.3)
    ax3.fill_between(fastest_df['lap_distance'], 0, fastest_df['brake'],
                     color='red', alpha=0.3)

    ax3.set_xlabel('Lap Distance (m)', fontsize=12)
    ax3.set_ylabel('Input (0-1)', fontsize=12)
    ax3.set_title(f'Throttle & Brake - Lap {fastest_lap_num} (Reference)',
                 fontsize=14, fontweight='bold')
    ax3.legend(loc='best', fontsize=10)
    ax3.grid(True, alpha=0.3)
    ax3.set_ylim(-0.1, 1.1)

    # Plot 4: Gear vs Distance for fastest lap
    ax4 = axes[1, 1]
    ax4.plot(fastest_df['lap_distance'], fastest_df['gear'],
            'b-', linewidth=2, alpha=0.8)
    ax4.fill_between(fastest_df['lap_distance'], 0, fastest_df['gear'],
                     color='blue', alpha=0.3)

    ax4.set_xlabel('Lap Distance (m)', fontsize=12)
    ax4.set_ylabel('Gear', fontsize=12)
    ax4.set_title(f'Gear Selection - Lap {fastest_lap_num} (Reference)',
                 fontsize=14, fontweight='bold')
    ax4.grid(True, alpha=0.3)
    ax4.set_ylim(0, 9)

    plt.tight_layout()

    # Save figure
    output_file = csv_file.replace('.csv', '_lap_analysis.png')
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    print(f"Lap analysis plot saved to: {output_file}")

    plt.show()

if __name__ == "__main__":
    # Get the most recent CSV file in logs directory
    logs_dir = "logs"

    if os.path.exists(logs_dir):
        csv_files = [os.path.join(logs_dir, f) for f in os.listdir(logs_dir)
                    if f.endswith('.csv') and not f.endswith('reference_lap.csv')]
        if csv_files:
            latest_csv = max(csv_files, key=os.path.getctime)
            analyze_laps(latest_csv)
        else:
            print("No CSV files found in logs directory!")
    else:
        print("logs directory not found!")
