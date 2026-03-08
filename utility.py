from tkinter import filedialog, Tk
def file_picker(file_types: str) -> str:
    """
    Opens a filedialog with supplied file_types
    Args:
        file_types (str): String of file types to accept when filedialog is open

    Returns:
        str: File path of the selected file

    """
    root = Tk()
    root.withdraw()
    root.attributes('-topmost', True)  # <-- Force to front
    root.update()                       # <-- Process the attribute change

    file_path = filedialog.askopenfilename(
        parent=root,                    # <-- Attach to root
        title="Select a football clip",
        filetypes=[
            ("Input", file_types),
            ("All files", "*.*")
        ]
    )

    root.destroy()
    return file_path