import os
import tkinter as tk
from tkinter import filedialog
from pydub import AudioSegment, generators
import threading
import time
import pyaudio
import queue

processed_audio = None
current_position = 0
pause_event = threading.Event()

# Create the pyaudio instance for audio playback
playback = pyaudio.PyAudio()
stream = None

playing = False
paused = False
current_position = 0
audio_queue = queue.Queue()

def slow_and_add_reverb(input_file, output_file, slowdown_factor=0.5, reverb_duration=1000, reverb_decay=0.5, reverb_type='sine'):
    global processed_audio
    # Input validation
    if not os.path.isfile(input_file):
        raise FileNotFoundError("Input file not found.")

    if not 0 < slowdown_factor <= 2.0:
        raise ValueError("Slowdown factor must be between 0 and 2 (exclusive).")

    if reverb_duration <= 0:
        raise ValueError("Reverb duration must be a positive value.")

    if not 0 <= reverb_decay <= 1.0:
        raise ValueError("Reverb decay must be between 0 and 1 (inclusive).")

    # Load the audio file
    audio = AudioSegment.from_file(input_file)

    # Slow down the audio
    slowed_audio = audio._spawn(audio.raw_data, overrides={
        "frame_rate": int(audio.frame_rate * slowdown_factor)
    }).set_frame_rate(audio.frame_rate)

    # Calculate the number of samples needed for the reverb duration
    reverb_samples = int(reverb_duration * slowed_audio.frame_rate / 1000)

    # Create the reverb effect
    if reverb_type == 'sine':
        reverb = generators.Sine(freq=440).to_audio_segment(duration=reverb_duration)
    elif reverb_type == 'convolution':
        reverb = AudioSegment.silent(duration=reverb_duration)
    else:
        raise ValueError("Invalid reverb type. Supported types are 'sine' and 'convolution'.")

    reverb = reverb.fade_out(int(reverb.duration_seconds * 1000 * reverb_decay))

    # Apply reverb to each channel separately for stereo audio
    if audio.channels == 2:
        # Split stereo audio into left and right channels
        left_channel, right_channel = slowed_audio.split_to_mono()

        # Apply reverb to each channel separately
        left_channel_with_reverb = left_channel.overlay(reverb, position=max(0, len(left_channel) - reverb_samples))
        right_channel_with_reverb = right_channel.overlay(reverb, position=max(0, len(right_channel) - reverb_samples))

        # Combine the channels back to stereo audio
        audio_with_reverb = left_channel_with_reverb.apply_gain_stereo(1, 0).overlay(right_channel_with_reverb.apply_gain_stereo(0, 1))
    else:
        # Apply reverb to the mono audio
        audio_with_reverb = slowed_audio.overlay(reverb, position=max(0, len(slowed_audio) - reverb_samples))

    # Export the final audio to the output file
    audio_with_reverb.export(output_file, format="mp3")

    # Store the processed audio in the global variable
    processed_audio = audio_with_reverb

    audio_queue.put(audio_with_reverb)
    return audio_with_reverb

def process_audio_live_preview():
    input_file = input_entry.get()
    slowdown_factor = float(slowdown_factor_scale.get())
    reverb_duration = int(reverb_duration_scale.get())
    reverb_decay = float(reverb_decay_scale.get())
    reverb_type = reverb_var.get()

    try:
        # Call the slow_and_add_reverb function with the correct arguments
        slow_and_add_reverb(input_file, "temp_output.mp3", slowdown_factor, reverb_duration, reverb_decay, reverb_type)
        global processed_audio
        # Play the processed audio
        audio = processed_audio
        if audio:
            playback.play(audio)

        # Clear the processed audio and free up memory

        processed_audio = None

        status_label.config(text="Live Preview: Adjusting modifiers...", fg="blue")
    except Exception as e:
        status_label.config(text=f"Error: {str(e)}", fg="red")

def on_slowdown_factor_change(event):
    process_audio_live_preview()

def on_reverb_duration_change(event):
    process_audio_live_preview()

def on_reverb_decay_change(event):
    process_audio_live_preview()

def on_reverb_type_change(event):
    process_audio_live_preview()

def browse_input_file():
    file_path = filedialog.askopenfilename(filetypes=[("Audio files", "*.mp3")])
    if file_path:
        input_entry.delete(0, tk.END)
        input_entry.insert(0, file_path)

def browse_output_dir():
    dir_path = filedialog.askdirectory()
    if dir_path:
        output_entry.delete(0, tk.END)
        output_entry.insert(0, dir_path)

def browse_output_file():
    file_path = filedialog.asksaveasfilename(defaultextension=".mp3", filetypes=[("Audio files", "*.mp3")])
    if file_path:
        output_entry.delete(0, tk.END)
        output_entry.insert(0, file_path)

def process_audio():
    input_file = input_entry.get()
    output_dir = output_entry.get()

    # Extract the chosen directory path from the output directory entry
    if not output_dir:
        status_label.config(text="Error: Output directory not selected.", fg="red")
        return

    # Check the file size before processing
    file_size = os.path.getsize(input_file)  # Get file size in bytes
    if file_size > 100 * 1024 * 1024:  # 100 MB limit (adjust as needed)
        status_label.config(text="Error: File size is too large for processing.", fg="red")
        return

    # Add a default output file name in the chosen directory
    output_file = os.path.join(output_dir, "processed_audio.mp3")

    slowdown_factor = float(slowdown_factor_scale.get())
    reverb_duration = int(reverb_duration_scale.get())
    reverb_decay = float(reverb_decay_scale.get())
    reverb_type = reverb_var.get()

    try:
        slow_and_add_reverb(input_file, output_file, slowdown_factor, reverb_duration, reverb_decay, reverb_type)
        status_label.config(text="Audio processing successful!", fg="green")
    except Exception as e:
        status_label.config(text=f"Error: {str(e)}", fg="red")

def play_audio_thread():
    global playing, paused, current_position

    audio_with_reverb = audio_queue.get()

    # Convert audio to raw PCM data
    raw_data = audio_with_reverb.raw_data

    # Play the audio using pyaudio
    stream = playback.open(
        format=playback.get_format_from_width(audio_with_reverb.sample_width),
        channels=audio_with_reverb.channels,
        rate=audio_with_reverb.frame_rate,
        output=True
    )

    # Start playing audio in a separate thread
    playing = True

    while current_position < len(raw_data) and playing:
        if not paused:
            chunk = raw_data[current_position:current_position + 1024]  # Read and play 1024 samples at a time
            stream.write(chunk)
            current_position += len(chunk)
        else:
            time.sleep(0.1)  # Sleep for a short duration to avoid busy waiting

    # Stop and close the audio stream
    stream.stop_stream()
    stream.close()

    # Reset the playback variables
    global playing, paused, current_position
    playing = False
    paused = False
    current_position = 0

def play_audio():
    global playing, paused

    if not playing:
        input_file = input_entry.get()
        output_file = "temp_output.mp3"  # Temporary output file for live preview
        slowdown_factor = float(slowdown_factor_scale.get())
        reverb_duration = int(reverb_duration_scale.get())
        reverb_decay = float(reverb_decay_scale.get())
        reverb_type = reverb_var.get()

        try:
            # Process audio and store it in the audio queue
            slow_and_add_reverb(input_file, output_file, slowdown_factor, reverb_duration, reverb_decay, reverb_type)

            # Start the playback in a separate thread
            play_thread = threading.Thread(target=play_audio_thread)
            play_thread.start()

            status_label.config(text="Playing...", fg="blue")

        except Exception as e:
            status_label.config(text=f"Error: {str(e)}", fg="red")

def pause_audio():
    global paused

    if playing:
        paused = not paused
        if paused:
            status_label.config(text="Paused", fg="blue")
        else:
            status_label.config(text="Playing...", fg="blue")

def close_pyaudio():
    global playback
    if playback:
        playback.terminate()
        playback = None

# Create the main application window
app = tk.Tk()
app.protocol("WM_DELETE_WINDOW", close_pyaudio)  # Call close_pyaudio when the window is closed
app.title("Audio Processing with Reverb")
app.geometry("480x660")


# Input file selection
input_label = tk.Label(app, text="Input Audio File:")
input_label.pack()
input_entry = tk.Entry(app, width=40)
input_entry.pack()
input_button = tk.Button(app, text="Browse", command=browse_input_file)
input_button.pack()

# Output file selection
output_label = tk.Label(app, text="Output Directory:")
output_label.pack()
output_entry = tk.Entry(app, width=40)
output_entry.pack()
output_button = tk.Button(app, text="Browse", command=browse_output_dir)
output_button.pack()

# Slowdown factor
slowdown_label = tk.Label(app, text="Slowdown Factor:")
slowdown_label.pack()
slowdown_factor_scale = tk.Scale(app, from_=0.1, to=2.0, resolution=0.1, orient=tk.HORIZONTAL, length=200)
slowdown_factor_scale.set(0.5)
slowdown_factor_scale.pack()

# Reverb duration
reverb_duration_label = tk.Label(app, text="Reverb Duration (ms):")
reverb_duration_label.pack()
reverb_duration_scale = tk.Scale(app, from_=100, to=5000, orient=tk.HORIZONTAL, length=200)
reverb_duration_scale.set(1000)
reverb_duration_scale.pack()

# Reverb decay
reverb_decay_label = tk.Label(app, text="Reverb Decay:")
reverb_decay_label.pack()
reverb_decay_scale = tk.Scale(app, from_=0.1, to=1.0, resolution=0.1, orient=tk.HORIZONTAL, length=200)
reverb_decay_scale.set(0.5)
reverb_decay_scale.pack()

# Reverb type
reverb_var = tk.StringVar(value="sine")
reverb_type_label = tk.Label(app, text="Reverb Type:")
reverb_type_label.pack()
reverb_type_sine_radio = tk.Radiobutton(app, text="Sine", variable=reverb_var, value="sine")
reverb_type_sine_radio.pack()
reverb_type_convolution_radio = tk.Radiobutton(app, text="Convolution", variable=reverb_var, value="convolution")
reverb_type_convolution_radio.pack()

# Status label
status_label = tk.Label(app, text="", fg="green")
status_label.pack()

# Play button
play_button = tk.Button(app, text="Preview Audio", command=play_audio)
play_button.pack()

# Pause button
pause_button = tk.Button(app, text="Play/Pause Audio", command=pause_audio)
pause_button.pack()

# Process button
process_button = tk.Button(app, text="Process Audio", command=process_audio)
process_button.pack()

slowdown_factor_scale.bind("<ButtonRelease-1>", on_slowdown_factor_change)
reverb_duration_scale.bind("<ButtonRelease-1>", on_reverb_duration_change)
reverb_decay_scale.bind("<ButtonRelease-1>", on_reverb_decay_change)
reverb_var.trace_add("write", on_reverb_type_change)

app.mainloop()
