import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { MobileAppProvider } from "@/context/MobileAppContext";
import { MOBILE_THEME } from "@/theme/tokens";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 20_000,
    },
  },
});

export default function RootLayout() {
  return (
    <SafeAreaProvider>
      <QueryClientProvider client={queryClient}>
        <MobileAppProvider>
          <StatusBar style="dark" />
          <Stack
            screenOptions={{
              headerShown: false,
              contentStyle: { backgroundColor: MOBILE_THEME.colors.ivoryCanvas },
            }}
          >
            <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
            <Stack.Screen name="branch/[id]" options={{ headerShown: false }} />
            <Stack.Screen name="hold/[id]" options={{ headerShown: false }} />
          </Stack>
        </MobileAppProvider>
      </QueryClientProvider>
    </SafeAreaProvider>
  );
}
