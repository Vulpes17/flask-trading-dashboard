import tkinter as tk
from tkinter import ttk

def main():
    root = tk.Tk()
    root.title("Test GUI")
    root.geometry("400x300")

    notebook = ttk.Notebook(root)
    frame1 = ttk.Frame(notebook)
    notebook.add(frame1, text="Tab 1")

    notebook.pack(expand=1, fill='both')
    tk.Label(frame1, text="Hello from Tab 1").pack(pady=20)

    root.mainloop()

if __name__ == "__main__":
    main()
