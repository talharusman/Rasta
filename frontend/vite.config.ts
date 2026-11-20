// OWNER: Member 4
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  envDir: "..", // read VITE_API_URL from the .env file in the project root
});
