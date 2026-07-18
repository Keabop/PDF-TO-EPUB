"""Interfaz gráfica mínima para convertir un PDF a EPUB.

Uso:
    python gui.py

Un solo flujo: elegís el PDF con "Seleccionar PDF…" y apretás "Convertir a
EPUB". El EPUB se guarda junto al PDF, con el mismo nombre. La conversión corre
en un hilo aparte para que la ventana no se congele con documentos grandes.

Requiere Tkinter, que viene incluido con las instalaciones estándar de Python
(en Windows y macOS ya está; en Linux puede necesitar `sudo apt install
python3-tk`).
"""

import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from main import convert, default_output_path


class ConverterApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.pdf_path: str | None = None
        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self.running = False

        root.title("PDF → EPUB para Kindle")
        root.minsize(560, 440)

        pad = {"padx": 16, "pady": 8}

        title = ttk.Label(
            root, text="Convertir PDF a EPUB", font=("", 16, "bold")
        )
        title.pack(anchor="w", **pad)

        # --- Selección de archivo ---
        file_frame = ttk.Frame(root)
        file_frame.pack(fill="x", **pad)

        self.select_btn = ttk.Button(
            file_frame, text="Seleccionar PDF…", command=self.pick_pdf
        )
        self.select_btn.pack(side="left")

        self.file_label = ttk.Label(
            file_frame, text="Ningún archivo seleccionado", foreground="#666"
        )
        self.file_label.pack(side="left", padx=12)

        # --- Botón principal ---
        self.convert_btn = ttk.Button(
            root,
            text="Convertir a EPUB",
            command=self.start_conversion,
            state="disabled",
        )
        self.convert_btn.pack(fill="x", padx=16, pady=(4, 8))

        # --- Barra de progreso indeterminada ---
        self.progress = ttk.Progressbar(root, mode="indeterminate")
        self.progress.pack(fill="x", padx=16, pady=(0, 8))

        # --- Log de progreso ---
        log_frame = ttk.Frame(root)
        log_frame.pack(fill="both", expand=True, padx=16, pady=(0, 12))

        self.log_text = tk.Text(
            log_frame, height=12, wrap="word", state="disabled",
            background="#f6f6f6", relief="flat",
        )
        scroll = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        self._poll_log_queue()

    # ------------------------------------------------------------------ #
    def pick_pdf(self) -> None:
        path = filedialog.askopenfilename(
            title="Elegí el PDF a convertir",
            filetypes=[("Archivos PDF", "*.pdf"), ("Todos", "*.*")],
        )
        if not path:
            return
        self.pdf_path = path
        self.file_label.configure(
            text=os.path.basename(path), foreground="#000"
        )
        self.convert_btn.configure(state="normal")

    def start_conversion(self) -> None:
        if self.running or not self.pdf_path:
            return
        self.running = True
        self.convert_btn.configure(state="disabled")
        self.select_btn.configure(state="disabled")
        self.progress.start(12)
        self._clear_log()

        output_path = default_output_path(self.pdf_path)
        image_dir = os.path.join(os.path.dirname(output_path), "images")

        thread = threading.Thread(
            target=self._run_conversion,
            args=(self.pdf_path, output_path, image_dir),
            daemon=True,
        )
        thread.start()

    def _run_conversion(self, pdf_path, output_path, image_dir) -> None:
        """Corre en un hilo aparte. Comunica resultados por la cola."""
        try:
            convert(
                pdf_path,
                output_path,
                image_dir,
                verbose=False,
                on_log=self.log_queue.put,
            )
            self.log_queue.put(f"__DONE__{output_path}")
        except Exception as exc:  # noqa: BLE001 - mostramos el error al usuario
            self.log_queue.put(f"__ERROR__{exc}")

    # ------------------------------------------------------------------ #
    def _poll_log_queue(self) -> None:
        try:
            while True:
                msg = self.log_queue.get_nowait()
                if msg.startswith("__DONE__"):
                    self._on_done(msg[len("__DONE__"):])
                elif msg.startswith("__ERROR__"):
                    self._on_error(msg[len("__ERROR__"):])
                else:
                    self._append_log(msg)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_log_queue)

    def _on_done(self, output_path: str) -> None:
        self.progress.stop()
        self.running = False
        self.convert_btn.configure(state="normal")
        self.select_btn.configure(state="normal")
        self._append_log(f"\n✓ Listo: {output_path}")
        messagebox.showinfo(
            "Conversión completa",
            f"EPUB generado:\n{output_path}\n\n"
            "Mandalo por Send to Kindle para leerlo en el dispositivo.",
        )

    def _on_error(self, message: str) -> None:
        self.progress.stop()
        self.running = False
        self.convert_btn.configure(state="normal")
        self.select_btn.configure(state="normal")
        self._append_log(f"\n✗ Error: {message}")
        messagebox.showerror("Error en la conversión", message)

    # --- helpers de log ---
    def _append_log(self, text: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")


def main() -> None:
    root = tk.Tk()
    ConverterApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
