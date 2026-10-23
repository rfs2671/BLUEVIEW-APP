import React from 'react';
import { View, StyleSheet } from 'react-native';
import CardSheen from './CardSheen';

/**
 * A View that carries the card sheen: for a box a screen draws itself (a record card, a credentials block) rather than
 * with GlassCard. It is a View in every respect (props, style, children), plus the sheen as its first child, laid over
 * the box's own fill by absolute position so it changes nothing about how the box lays out its content. The corner radius
 * is read from the box's own style.
 */
export default function SheenView({ style, children, depth, intro = true, ...rest }) {
  const radius = (StyleSheet.flatten(style) || {}).borderRadius;
  return (
    <View {...rest} style={style}>
      <CardSheen radius={typeof radius === 'number' ? radius : 14} depth={depth} intro={intro} />
      {children}
    </View>
  );
}
