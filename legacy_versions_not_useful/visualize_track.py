import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import sys
import os

def plot_track(csv_file):
    """Plot track map from telemetry data."""
    
    # Load data
    print(f"Loading {csv_file}...")
    df = pd.read_csv(csv_file)
    print(f"Loaded {len(df)} telemetry points")
    
    # Extract position data
    x = df['pos_x'].values
    z = df['pos_z'].values
    speed = df['speed'].values
    
    # Create figure with two subplots
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 8))
    
    # Plot 1: Track map colored by speed
    scatter = ax1.scatter(x, z, c=speed, cmap='RdYlGn', s=1, alpha=0.6)
    ax1.set_xlabel('X Position (m)', fontsize=12)
    ax1.set_ylabel('Z Position (m)', fontsize=12)
    ax1.set_title('Track Map - Colored by Speed', fontsize=14, fontweight='bold')
    ax1.set_aspect('equal')
    ax1.grid(True, alpha=0.3)
    
    # Add colorbar
    cbar = plt.colorbar(scatter, ax=ax1)
    cbar.set_label('Speed (km/h)', fontsize=10)
    
    # Plot 2: Track map with arrows showing direction
    # Downsample for clarity
    step = max(1, len(x) // 500)
    ax2.plot(x, z, 'b-', linewidth=0.5, alpha=0.3)
    
    # Calculate direction vectors
    x_sample = x[::step]
    z_sample = z[::step]
    dx = np.diff(x_sample)
    dz = np.diff(z_sample)
    
    # Plot arrows (one less than sample points)
    ax2.quiver(x_sample[:-1], z_sample[:-1], dx, dz,
               scale_units='xy', scale=1, width=0.003, 
               headwidth=3, headlength=4, color='darkblue', alpha=0.7)
    
    ax2.set_xlabel('X Position (m)', fontsize=12)
    ax2.set_ylabel('Z Position (m)', fontsize=12)
    ax2.set_title('Track Map - With Direction', fontsize=14, fontweight='bold')
    ax2.set_aspect('equal')
    ax2.grid(True, alpha=0.3)
    
    plt.tight_layout()
    
    # Save figure
    output_file = csv_file.replace('.csv', '_track_map.png')
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    print(f"\nTrack map saved to: {output_file}")
    
    # Show statistics
    print("\n" + "="*60)
    print("TRACK STATISTICS:")
    print("="*60)
    print(f"Total telemetry points: {len(df):,}")
    print(f"Duration: {df['session_time'].max() - df['session_time'].min():.1f} seconds")
    print(f"Speed range: {speed.min():.0f} - {speed.max():.0f} km/h")
    print(f"Average speed: {speed.mean():.0f} km/h")
    print(f"Track bounds:")
    print(f"  X: {x.min():.1f} to {x.max():.1f} m (range: {x.max()-x.min():.1f} m)")
    print(f"  Z: {z.min():.1f} to {z.max():.1f} m (range: {z.max()-z.min():.1f} m)")
    print("="*60)
    
    plt.show()

if __name__ == "__main__":
    # Get the most recent CSV file in logs directory
    logs_dir = "logs"
    
    if os.path.exists(logs_dir):
        csv_files = [os.path.join(logs_dir, f) for f in os.listdir(logs_dir) if f.endswith('.csv')]
        if csv_files:
            latest_csv = max(csv_files, key=os.path.getctime)
            plot_track(latest_csv)
        else:
            print("No CSV files found in logs directory!")
    else:
        print("logs directory not found!")