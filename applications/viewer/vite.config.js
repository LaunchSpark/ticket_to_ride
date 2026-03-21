import { defineConfig } from "vite";

const pollingInterval = Number.parseInt(process.env.VITE_POLLING_INTERVAL_MS || "300", 10);

export default defineConfig({
  server: {
    host: "0.0.0.0",
    hmr: {
      host: "127.0.0.1",
      clientPort: Number.parseInt(process.env.TICKET_TO_RIDE_VIEWER_PORT || "4173", 10),
    },
    watch: {
      usePolling: true,
      useFsEvents: false,
      interval: Number.isNaN(pollingInterval) ? 300 : pollingInterval,
    },
  },
});
