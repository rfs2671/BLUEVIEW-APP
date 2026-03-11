import React, { useState, useRef, useCallback } from 'react';
import {
  View,
  Text,
  TextInput,
  Pressable,
  FlatList,
  ActivityIndicator,
  StyleSheet,
} from 'react-native';
import { MapPin } from 'lucide-react-native';
import apiClient from '../utils/api';
import { spacing, borderRadius, typography } from '../styles/theme';
import { useTheme } from '../context/ThemeContext';

const DEBOUNCE_MS = 350;

export default function AddressAutocomplete({
  value = '',
  onChangeText,
  onSelect,
  placeholder = 'Start typing an address...',
  style,
}) {
  const { colors, isDark } = useTheme();
  const s = buildStyles(colors, isDark);
  const [suggestions, setSuggestions] = useState([]);
  const [loading, setLoading] = useState(false);
  const [showDropdown, setShowDropdown] = useState(false);
  const debounceRef = useRef(null);

  const fetchSuggestions = useCallback(async (query) => {
    if (!query || query.length < 3) {
      setSuggestions([]);
      setShowDropdown(false);
      return;
    }

    setLoading(true);
    try {
      const response = await apiClient.get('/api/places/autocomplete', {
        params: { input: query, types: 'address' },
      });
      const results = response.data?.predictions || response.data || [];
      setSuggestions(results);
      setShowDropdown(results.length > 0);
    } catch (error) {
      console.error('Address autocomplete failed:', error);
      setSuggestions([]);
      setShowDropdown(false);
    } finally {
      setLoading(false);
    }
  }, []);

  const handleChangeText = (text) => {
    onChangeText?.(text);

    // Debounce API calls
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => fetchSuggestions(text), DEBOUNCE_MS);
  };

  const handleSelect = (suggestion) => {
    const fullAddress = suggestion.description || suggestion.formatted_address || suggestion.name || '';
    onChangeText?.(fullAddress);
    onSelect?.({ address: fullAddress, placeId: suggestion.place_id || null });
    setShowDropdown(false);
    setSuggestions([]);
  };

  return (
    <View style={[s.container, style]}>
      <View style={s.inputRow}>
        <MapPin size={16} strokeWidth={1.5} color={colors.text.muted} style={s.icon} />
        <TextInput
          style={s.input}
          value={value}
          onChangeText={handleChangeText}
          placeholder={placeholder}
          placeholderTextColor={colors.text.subtle}
          autoCapitalize="words"
          autoCorrect={false}
          onFocus={() => {
            if (suggestions.length > 0) setShowDropdown(true);
          }}
          onBlur={() => {
            // Delay hiding so tap on suggestion registers
            setTimeout(() => setShowDropdown(false), 200);
          }}
        />
        {loading && <ActivityIndicator size="small" color={colors.text.muted} style={s.spinner} />}
      </View>

      {showDropdown && suggestions.length > 0 && (
        <View style={s.dropdown}>
          <FlatList
            data={suggestions}
            keyExtractor={(item, index) => item.place_id || `suggestion-${index}`}
            keyboardShouldPersistTaps="handled"
            nestedScrollEnabled
            renderItem={({ item }) => (
              <Pressable
                style={s.suggestionRow}
                onPress={() => handleSelect(item)}
              >
                <MapPin size={14} strokeWidth={1.5} color={colors.text.muted} />
                <View style={s.suggestionTextWrap}>
                  <Text style={s.suggestionMain} numberOfLines={1}>
                    {item.structured_formatting?.main_text || item.description?.split(',')[0] || item.description}
                  </Text>
                  <Text style={s.suggestionSecondary} numberOfLines={1}>
                    {item.structured_formatting?.secondary_text ||
                      item.description?.split(',').slice(1).join(',').trim() ||
                      ''}
                  </Text>
                </View>
              </Pressable>
            )}
          />
        </View>
      )}
    </View>
  );
}

function buildStyles(colors, isDark) {
  return StyleSheet.create({
  container: {
    position: 'relative',
    zIndex: 100,
  },
  inputRow: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.glass.background,
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: colors.glass.border,
    paddingHorizontal: spacing.md,
    height: 48,
  },
  icon: {
    marginRight: spacing.sm,
  },
  input: {
    flex: 1,
    fontSize: 15,
    color: colors.text.primary,
  },
  spinner: {
    marginLeft: spacing.sm,
  },
  dropdown: {
    position: 'absolute',
    top: 52,
    left: 0,
    right: 0,
    backgroundColor: colors.glass.background,
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: colors.glass.border,
    maxHeight: 220,
    overflow: 'hidden',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.3,
    shadowRadius: 8,
    elevation: 8,
    zIndex: 999,
  },
  suggestionRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: spacing.sm + 2,
    paddingHorizontal: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.border.subtle,
    gap: spacing.sm,
  },
  suggestionTextWrap: {
    flex: 1,
  },
  suggestionMain: {
    fontSize: 14,
    fontWeight: '500',
    color: colors.text.primary,
  },
  suggestionSecondary: {
    fontSize: 12,
    color: colors.text.muted,
    marginTop: 1,
  },
});
}

