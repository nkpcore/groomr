import { Tabs } from "expo-router";
import { CalendarCheck, Compass, User } from "lucide-react-native";
import { useMobileApp } from "@/context/MobileAppContext";
import { MOBILE_THEME } from "@/theme/tokens";

export default function CustomerTabsLayout() {
  const { t } = useMobileApp();

  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: MOBILE_THEME.colors.olivePrimary,
        tabBarInactiveTintColor: MOBILE_THEME.colors.charcoalMuted,
        tabBarStyle: {
          backgroundColor: MOBILE_THEME.colors.ivoryCanvas,
          borderTopColor: MOBILE_THEME.colors.ivoryBorder,
          borderTopWidth: 1,
          minHeight: 64,
          paddingTop: 6,
          paddingBottom: 8,
        },
        tabBarLabelStyle: {
          fontSize: 12,
          fontWeight: "600",
        },
      }}
    >
      <Tabs.Screen
        name="index"
        options={{
          title: t.navigation.exploreTab,
          tabBarIcon: ({ color, size }) => <Compass size={size} color={color} />,
        }}
      />
      <Tabs.Screen
        name="bookings"
        options={{
          title: t.navigation.bookingsTab,
          tabBarIcon: ({ color, size }) => <CalendarCheck size={size} color={color} />,
        }}
      />
      <Tabs.Screen
        name="account"
        options={{
          title: t.navigation.accountTab,
          tabBarIcon: ({ color, size }) => <User size={size} color={color} />,
        }}
      />
    </Tabs>
  );
}
