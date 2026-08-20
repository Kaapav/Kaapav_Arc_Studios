import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:kaapav_control_room/main.dart';

void main() {
  testWidgets('renders the KAAPAV neumorphic page heading', (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: PageTitle(
            title: 'Studio pulse',
            subtitle: 'Live production intelligence',
          ),
        ),
      ),
    );

    expect(find.text('Studio pulse'), findsOneWidget);
    expect(find.text('Live production intelligence'), findsOneWidget);
  });
}
