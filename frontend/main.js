// Processo principale di Electron.
//
// Si limita a creare la finestra dell'applicazione e a caricare la UI
// locale (index.html). Tutta la logica applicativa vive nel renderer
// (renderer.js), che comunica con il backend FastAPI locale su
// http://localhost:8000.

const { app, BrowserWindow } = require("electron");
const path = require("path");

function createWindow() {
  const mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    minWidth: 900,
    minHeight: 600,
    title: "TCG Artwork Outpainting",
    webPreferences: {
      // La UI è statica e non necessita di accesso privilegiato a Node,
      // ma abilitiamo contextIsolation di default per sicurezza.
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  mainWindow.loadFile(path.join(__dirname, "index.html"));

  // Utile in sviluppo; puoi rimuovere/commentare questa riga in produzione.
  // mainWindow.webContents.openDevTools();
}

app.whenReady().then(createWindow);

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow();
  }
});
