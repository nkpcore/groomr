import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "CHAIR Business",
    short_name: "CHAIR Biz",
    description: "Manage chairs, shifts, walk-ins, and verified bookings.",
    start_url: "/partner",
    display: "standalone",
    background_color: "#FAF7F2",
    theme_color: "#1C1B19",
  };
}
