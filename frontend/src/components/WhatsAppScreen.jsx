import React from 'react';
import { View, Text, StyleSheet, ScrollView } from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { ArrowLeft } from 'lucide-react-native';
import AnimatedBackground from './AnimatedBackground';
import GlassButton from './GlassButton';
import HeaderBrand from './HeaderBrand';
import { spacing, typography } from '../styles/theme';
import { withAlpha } from '../styles/semanticColors';
import { useTheme } from '../context/ThemeContext';

/** The frame of Integrations → WhatsApp → Project groups / Personal assistant. */
export default function WhatsAppScreen({ title, children }) {
  const { colors } = useTheme();
  const s = buildStyles(colors);
  const router = useRouter();
  const back = () => (router.canGoBack() ? router.back() : router.push('/admin/integrations'));
  return (
    <AnimatedBackground>
      <SafeAreaView style={s.container} edges={['top']}>
        <View style={s.header}>
          <View style={s.headerLeft}>
            <GlassButton
              variant="icon"
              icon={<ArrowLeft size={20} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={back}
            />
            <HeaderBrand />
          </View>
        </View>
        <ScrollView style={s.scrollView} contentContainerStyle={s.scrollContent}
          showsVerticalScrollIndicator={false}>
          <View style={s.titleSection}>
            <Text style={s.titleLabel}>WHATSAPP</Text>
            <Text style={s.titleText}>{title}</Text>
          </View>
          {children}
        </ScrollView>
      </SafeAreaView>
    </AnimatedBackground>
  );
}

function buildStyles(colors) {
  return StyleSheet.create({
    container: { flex: 1 },
    header: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      paddingHorizontal: spacing.lg,
      paddingVertical: spacing.md,
      borderBottomWidth: 1,
      borderBottomColor: withAlpha('#ffffff', 0.08),
    },
    headerLeft: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
    scrollView: { flex: 1 },
    scrollContent: { padding: spacing.lg, paddingBottom: 120 },
    titleSection: { marginBottom: spacing.xl },
    titleLabel: { ...typography.label, color: colors.text.muted, marginBottom: spacing.sm },
    titleText: { fontSize: 36, fontWeight: '200', color: colors.text.primary, letterSpacing: -1 },
  });
}
