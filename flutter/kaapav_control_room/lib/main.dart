import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';

void main() => runApp(const KaapavControlRoomApp());

const _bg = Color(0xFFE9EFF8);
const _ink = Color(0xFF20283A);
const _muted = Color(0xFF71809B);
const _violet = Color(0xFF675CF5);
const _pink = Color(0xFFFF5EA8);
const _cyan = Color(0xFF18B8C9);
const _amber = Color(0xFFFFA928);
const _green = Color(0xFF24B77A);
const _red = Color(0xFFF05D68);

class KaapavControlRoomApp extends StatelessWidget {
  const KaapavControlRoomApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'KAAPAV Control Room',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        useMaterial3: true,
        scaffoldBackgroundColor: _bg,
        colorScheme: ColorScheme.fromSeed(
          seedColor: _violet,
          brightness: Brightness.light,
          surface: _bg,
        ),
        textTheme: ThemeData.light().textTheme.apply(
          bodyColor: _ink,
          displayColor: _ink,
          fontFamily: 'Segoe UI',
        ),
      ),
      home: const ControlRoom(),
    );
  }
}

class DashboardApi {
  DashboardApi()
    : baseUrl = Platform.isWindows
          ? 'http://127.0.0.1:8765'
          : 'https://yt.kaapav.com' {
    client.connectionTimeout = const Duration(seconds: 10);
  }

  final String baseUrl;
  final HttpClient client = HttpClient();
  String? sessionCookie;

  File get _sessionFile {
    final home =
        Platform.environment['HOME'] ??
        Platform.environment['LOCALAPPDATA'] ??
        Directory.systemTemp.path;
    return File('$home${Platform.pathSeparator}.kaapav_dashboard_session');
  }

  Future<void> restoreSession() async {
    try {
      final value = (await _sessionFile.readAsString()).trim();
      if (value.isNotEmpty) sessionCookie = value;
    } catch (_) {
      // A missing session is the normal first-run state.
    }
  }

  Future<Map<String, dynamic>> status() async {
    final response = await _request('/api/status');
    if (response.statusCode == 401) throw const PairingRequired();
    if (response.statusCode != 200) {
      throw HttpException('Dashboard returned HTTP ${response.statusCode}');
    }
    return jsonDecode(await utf8.decodeStream(response))
        as Map<String, dynamic>;
  }

  Future<void> pair(String code) async {
    final response = await _request(
      '/auth/bootstrap?code=${Uri.encodeQueryComponent(code.trim())}',
      followRedirects: false,
    );
    if (response.statusCode != 302) {
      throw const FormatException(
        'Pairing code is invalid, expired, or already used.',
      );
    }
    final setCookie = response.headers.value(HttpHeaders.setCookieHeader) ?? '';
    final cookie = setCookie.split(';').first.trim();
    if (!cookie.startsWith('kaapav_dashboard_session=')) {
      throw const FormatException('The secure session was not returned.');
    }
    await response.drain<void>();
    sessionCookie = cookie;
    await _sessionFile.writeAsString(cookie, flush: true);
  }

  Future<void> platformControl(String platform, bool enabled) async {
    final request = await client.postUrl(
      Uri.parse('$baseUrl/api/platform-control'),
    );
    request.headers.set(HttpHeaders.acceptHeader, 'application/json');
    request.headers.set(HttpHeaders.contentTypeHeader, 'application/json');
    request.headers.set('X-KAAPAV-Control', 'confirmed');
    if (sessionCookie != null) {
      request.headers.set(HttpHeaders.cookieHeader, sessionCookie!);
    }
    request.write(
      jsonEncode({
        'platform': platform,
        'action': enabled ? 'enable' : 'disable',
      }),
    );
    final response = await request.close();
    final payload =
        jsonDecode(await utf8.decodeStream(response)) as Map<String, dynamic>;
    if (response.statusCode != 200 || payload['ok'] != true) {
      throw StateError(
        textOf(
          payload['detail'] ?? payload['error'],
          'Platform control failed',
        ),
      );
    }
  }

  Future<void> automationControl(bool enabled) async {
    final request = await client.postUrl(
      Uri.parse('$baseUrl/api/autopilot-control'),
    );
    request.headers.set(HttpHeaders.acceptHeader, 'application/json');
    request.headers.set(HttpHeaders.contentTypeHeader, 'application/json');
    request.headers.set('X-KAAPAV-Control', 'confirmed');
    if (sessionCookie != null) {
      request.headers.set(HttpHeaders.cookieHeader, sessionCookie!);
    }
    request.write(jsonEncode({'action': enabled ? 'enable' : 'disable'}));
    final response = await request.close();
    final payload =
        jsonDecode(await utf8.decodeStream(response)) as Map<String, dynamic>;
    if (response.statusCode != 200 || payload['ok'] != true) {
      throw StateError(textOf(payload['error'], 'Automation control failed'));
    }
  }

  Future<HttpClientResponse> _request(
    String route, {
    bool followRedirects = true,
  }) async {
    try {
      final request = await client.getUrl(Uri.parse('$baseUrl$route'));
      request.followRedirects = followRedirects;
      request.headers.set(HttpHeaders.acceptHeader, 'application/json');
      if (sessionCookie != null) {
        request.headers.set(HttpHeaders.cookieHeader, sessionCookie!);
      }
      return await request.close();
    } catch (_) {
      rethrow;
    }
  }
}

class PairingRequired implements Exception {
  const PairingRequired();
}

class ControlRoom extends StatefulWidget {
  const ControlRoom({super.key});

  @override
  State<ControlRoom> createState() => _ControlRoomState();
}

class _ControlRoomState extends State<ControlRoom> {
  final api = DashboardApi();
  final search = TextEditingController();
  Timer? timer;
  Map<String, dynamic>? data;
  Object? error;
  bool pairingRequired = false;
  bool loading = true;
  int tab = 0;

  static const tabs = [
    ('Overview', Icons.space_dashboard_rounded, _violet),
    ('Production', Icons.movie_creation_rounded, _pink),
    ('Releases', Icons.rocket_launch_rounded, _cyan),
    ('Performance', Icons.auto_graph_rounded, _amber),
    ('System', Icons.shield_rounded, _green),
  ];

  @override
  void initState() {
    super.initState();
    _start();
  }

  Future<void> _start() async {
    await api.restoreSession();
    await refresh();
    timer = Timer.periodic(
      const Duration(seconds: 5),
      (_) => refresh(silent: true),
    );
  }

  Future<void> refresh({bool silent = false}) async {
    if (!silent && mounted) setState(() => loading = true);
    try {
      final next = await api.status();
      if (!mounted) return;
      setState(() {
        data = next;
        error = null;
        pairingRequired = false;
        loading = false;
      });
    } on PairingRequired catch (caught) {
      if (!mounted) return;
      setState(() {
        error = caught;
        pairingRequired = true;
        loading = false;
      });
    } catch (caught) {
      if (!mounted) return;
      setState(() {
        error = caught;
        loading = false;
      });
    }
  }

  Future<void> changePlatform(String platform, bool enabled) async {
    try {
      await api.platformControl(platform, enabled);
      await refresh(silent: true);
    } catch (caught) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('$platform control failed: $caught')),
      );
    }
  }

  Future<void> changeAutomation(bool enabled) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: Text(enabled ? 'Enable automation?' : 'Disable automation?'),
        content: Text(
          enabled
              ? 'Open the production gate and start the next supervised cycle.'
              : 'Close the production gate and stop scheduled production safely.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            child: Text(enabled ? 'Enable' : 'Disable'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    try {
      await api.automationControl(enabled);
      await refresh(silent: true);
    } catch (caught) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Automation control failed: $caught')),
      );
    }
  }

  @override
  void dispose() {
    timer?.cancel();
    search.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, box) {
        final wide = box.maxWidth >= 940;
        final page = _page();
        return Scaffold(
          body: SafeArea(
            child: Row(
              children: [
                if (wide) _sideNavigation(),
                Expanded(
                  child: Column(
                    children: [
                      _header(),
                      Expanded(child: page),
                    ],
                  ),
                ),
              ],
            ),
          ),
          bottomNavigationBar: wide ? null : _bottomNavigation(),
        );
      },
    );
  }

  Widget _page() {
    if (loading && data == null) {
      return const Center(child: CircularProgressIndicator(color: _violet));
    }
    if (pairingRequired) {
      return PairingView(api: api, onPaired: () => refresh());
    }
    if (data == null) {
      return ErrorView(message: '$error', onRetry: () => refresh());
    }
    return RefreshIndicator(
      onRefresh: refresh,
      color: _violet,
      child: switch (tab) {
        0 => OverviewPage(
          data: data!,
          onPlatform: changePlatform,
          onAutomation: changeAutomation,
        ),
        1 => ProductionPage(data: data!, search: search),
        2 => ReleasesPage(data: data!),
        3 => PerformancePage(data: data!),
        _ => SystemPage(data: data!),
      },
    );
  }

  Widget _header() {
    final studio = map(data?['studio']);
    final paused = textOf(studio['mode'], 'CONNECTING') == 'PAUSED';
    return Padding(
      padding: const EdgeInsets.fromLTRB(22, 18, 22, 10),
      child: Row(
        children: [
          Container(
            width: 48,
            height: 48,
            decoration: const BoxDecoration(
              gradient: LinearGradient(colors: [_violet, _pink]),
              borderRadius: BorderRadius.all(Radius.circular(16)),
              boxShadow: [
                BoxShadow(
                  color: Color(0x50675CF5),
                  blurRadius: 18,
                  offset: Offset(0, 8),
                ),
              ],
            ),
            child: const Icon(Icons.auto_awesome_rounded, color: Colors.white),
          ),
          const SizedBox(width: 14),
          const Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'KAAPAV CONTROL ROOM',
                  style: TextStyle(
                    fontWeight: FontWeight.w900,
                    letterSpacing: 1.1,
                    fontSize: 18,
                  ),
                ),
                Text(
                  'ARC Studios · live production intelligence',
                  style: TextStyle(color: _muted, fontSize: 12),
                ),
              ],
            ),
          ),
          StatusPill(
            label: paused
                ? 'PAUSED SAFE'
                : textOf(studio['mode'], 'CONNECTING'),
            color: paused ? _amber : _green,
          ),
          const SizedBox(width: 8),
          SoftIconButton(icon: Icons.refresh_rounded, onTap: refresh),
        ],
      ),
    );
  }

  Widget _sideNavigation() {
    return Container(
      width: 104,
      margin: const EdgeInsets.all(16),
      decoration: softDecoration(radius: 28),
      child: Column(
        children: [
          const SizedBox(height: 18),
          const Text(
            'K',
            style: TextStyle(
              fontSize: 28,
              fontWeight: FontWeight.w900,
              color: _violet,
            ),
          ),
          const Spacer(),
          for (var index = 0; index < tabs.length; index++)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 7),
              child: NavButton(
                icon: tabs[index].$2,
                label: tabs[index].$1,
                color: tabs[index].$3,
                selected: tab == index,
                onTap: () => setState(() => tab = index),
              ),
            ),
          const Spacer(),
          const Icon(Icons.lock_rounded, color: _green, size: 18),
          const SizedBox(height: 18),
        ],
      ),
    );
  }

  Widget _bottomNavigation() {
    return Container(
      decoration: const BoxDecoration(
        color: _bg,
        boxShadow: [BoxShadow(color: Color(0x22000000), blurRadius: 20)],
      ),
      child: NavigationBar(
        height: 72,
        backgroundColor: _bg,
        indicatorColor: tabs[tab].$3.withValues(alpha: .16),
        selectedIndex: tab,
        onDestinationSelected: (value) => setState(() => tab = value),
        destinations: [
          for (final item in tabs)
            NavigationDestination(
              icon: Icon(item.$2),
              selectedIcon: Icon(item.$2, color: item.$3),
              label: item.$1,
            ),
        ],
      ),
    );
  }
}

class OverviewPage extends StatelessWidget {
  const OverviewPage({
    super.key,
    required this.data,
    required this.onPlatform,
    required this.onAutomation,
  });
  final Map<String, dynamic> data;
  final Future<void> Function(String platform, bool enabled) onPlatform;
  final Future<void> Function(bool enabled) onAutomation;

  @override
  Widget build(BuildContext context) {
    final overview = map(data['overview']);
    final studio = map(data['studio']);
    final next = map(studio['next_task']);
    final platforms = map(data['platforms']);
    final paused = studio['pause_file'] == true;
    return PageList(
      children: [
        const PageTitle(
          title: 'Studio pulse',
          subtitle: 'The whole operation in one clean glance',
        ),
        MetricGrid(
          metrics: [
            Metric(
              'Series',
              overview['series'],
              Icons.collections_bookmark_rounded,
              _violet,
            ),
            Metric(
              'Episodes',
              overview['episode_manifests'],
              Icons.movie_filter_rounded,
              _pink,
            ),
            Metric(
              'Public',
              overview['public_videos'],
              Icons.public_rounded,
              _cyan,
            ),
            Metric(
              'Total views',
              overview['total_views'],
              Icons.visibility_rounded,
              _amber,
            ),
            Metric(
              'Images ready',
              '${overview['images_complete']}/${overview['images_total']}',
              Icons.image_rounded,
              _green,
            ),
            Metric(
              'Buffer',
              '${overview['ready_buffer']}/${overview['buffer_target']}',
              Icons.inventory_2_rounded,
              _red,
            ),
          ],
        ),
        SoftPanel(
          color: paused ? _amber : _green,
          child: Row(
            children: [
              Icon(
                paused
                    ? Icons.pause_circle_rounded
                    : Icons.power_settings_new_rounded,
                color: paused ? _amber : _green,
                size: 34,
              ),
              const SizedBox(width: 14),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Automation ${paused ? 'disabled' : 'enabled'}',
                      style: const TextStyle(fontWeight: FontWeight.w900),
                    ),
                    Text(
                      paused
                          ? 'Production gate is safely closed.'
                          : 'Zero-touch production gate is open.',
                      style: const TextStyle(color: _muted, fontSize: 12),
                    ),
                  ],
                ),
              ),
              FilledButton(
                onPressed: () => onAutomation(paused),
                style: FilledButton.styleFrom(
                  backgroundColor: paused ? _green : _red,
                ),
                child: Text(paused ? 'Enable' : 'Disable'),
              ),
            ],
          ),
        ),
        SoftPanel(
          color: _cyan,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const SectionLabel(
                icon: Icons.hub_rounded,
                title: 'Platform controls',
                color: _cyan,
              ),
              const SizedBox(height: 12),
              for (final name in const ['youtube', 'facebook', 'instagram'])
                Builder(
                  builder: (context) {
                    final platform = map(platforms[name]);
                    final enabled = platform['enabled'] == true;
                    return Container(
                      margin: const EdgeInsets.only(bottom: 10),
                      padding: const EdgeInsets.symmetric(
                        horizontal: 14,
                        vertical: 10,
                      ),
                      decoration: pressedDecoration(_cyan),
                      child: Row(
                        children: [
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  name.toUpperCase(),
                                  style: const TextStyle(
                                    fontWeight: FontWeight.w900,
                                  ),
                                ),
                                Text(
                                  '${textOf(platform['health'], 'unknown')} · queued ${platform['queued'] ?? 0} · issues ${platform['failures'] ?? 0}',
                                  style: const TextStyle(
                                    color: _muted,
                                    fontSize: 11,
                                  ),
                                ),
                              ],
                            ),
                          ),
                          Switch(
                            value: enabled,
                            activeThumbColor: _green,
                            onChanged: (value) => onPlatform(name, value),
                          ),
                        ],
                      ),
                    );
                  },
                ),
            ],
          ),
        ),
        SoftPanel(
          color: _violet,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const SectionLabel(
                icon: Icons.bolt_rounded,
                title: 'Next exact action',
                color: _violet,
              ),
              const SizedBox(height: 14),
              Text(
                textOf(next['episode_title'], 'No task queued'),
                style: const TextStyle(
                  fontSize: 20,
                  fontWeight: FontWeight.w800,
                ),
              ),
              const SizedBox(height: 8),
              Text(
                '${textOf(next['action'], 'waiting').replaceAll('_', ' ')} · ${textOf(next['state'], 'safe')}',
                style: const TextStyle(color: _muted),
              ),
              const SizedBox(height: 16),
              LinearProgressIndicator(
                value: numberOf(overview['image_progress_percent']) / 100,
                minHeight: 11,
                borderRadius: BorderRadius.circular(20),
                color: _violet,
                backgroundColor: const Color(0xFFD6DEEB),
              ),
              const SizedBox(height: 8),
              Text(
                '${overview['image_progress_percent']}% visual inventory complete',
                style: const TextStyle(color: _muted, fontSize: 12),
              ),
            ],
          ),
        ),
        SoftPanel(
          color: _amber,
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Icon(Icons.shield_moon_rounded, color: _amber, size: 32),
              const SizedBox(width: 14),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      textOf(studio['mode'], 'UNKNOWN'),
                      style: const TextStyle(
                        fontWeight: FontWeight.w900,
                        fontSize: 17,
                      ),
                    ),
                    const SizedBox(height: 5),
                    Text(
                      textOf(studio['summary']),
                      style: const TextStyle(color: _muted, height: 1.4),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class ProductionPage extends StatefulWidget {
  const ProductionPage({super.key, required this.data, required this.search});
  final Map<String, dynamic> data;
  final TextEditingController search;

  @override
  State<ProductionPage> createState() => _ProductionPageState();
}

class _ProductionPageState extends State<ProductionPage> {
  @override
  Widget build(BuildContext context) {
    final production = map(widget.data['production']);
    final series = listOf(production['series']);
    final query = widget.search.text.trim().toLowerCase();
    final episodes = listOf(production['episodes']).where((raw) {
      final item = map(raw);
      return query.isEmpty ||
          '${item['series_title']} ${item['episode']} ${item['episode_title']} ${item['state']} ${item['blocker']}'
              .toLowerCase()
              .contains(query);
    }).toList();
    return PageList(
      children: [
        const PageTitle(
          title: 'Production pipeline',
          subtitle: 'Every series, episode, blocker and next move',
        ),
        SoftPanel(
          child: TextField(
            controller: widget.search,
            onChanged: (_) => setState(() {}),
            decoration: const InputDecoration(
              prefixIcon: Icon(Icons.search_rounded, color: _violet),
              hintText: 'Search 300 episodes…',
              border: InputBorder.none,
            ),
          ),
        ),
        const SectionTitle('Series progress'),
        for (final raw in series)
          Builder(
            builder: (_) {
              final item = map(raw);
              final value = numberOf(item['progress_percent']) / 100;
              return SoftPanel(
                color: _violet,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Expanded(
                          child: Text(
                            '${item['sequence']}. ${item['title']}',
                            style: const TextStyle(fontWeight: FontWeight.w800),
                          ),
                        ),
                        Text(
                          '${item['release_ready']}/${item['episodes']}',
                          style: const TextStyle(
                            color: _violet,
                            fontWeight: FontWeight.w800,
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 10),
                    LinearProgressIndicator(
                      value: value,
                      minHeight: 9,
                      borderRadius: BorderRadius.circular(12),
                      color: _violet,
                      backgroundColor: const Color(0xFFD5DDEA),
                    ),
                  ],
                ),
              );
            },
          ),
        SectionTitle('${episodes.length} matching episodes'),
        for (final raw in episodes)
          Builder(
            builder: (_) {
              final item = map(raw);
              final state = textOf(item['state']);
              final color = statusColor(state);
              return SoftPanel(
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    CircleAvatar(
                      backgroundColor: color.withValues(alpha: .14),
                      foregroundColor: color,
                      child: Text(
                        '${item['episode']}',
                        style: const TextStyle(fontWeight: FontWeight.w900),
                      ),
                    ),
                    const SizedBox(width: 14),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            textOf(item['episode_title']),
                            style: const TextStyle(fontWeight: FontWeight.w700),
                          ),
                          const SizedBox(height: 5),
                          Text(
                            textOf(item['series_title']),
                            style: const TextStyle(color: _muted, fontSize: 12),
                          ),
                          if (item['blocker'] != null) ...[
                            const SizedBox(height: 6),
                            Text(
                              textOf(item['blocker']),
                              style: const TextStyle(color: _red, fontSize: 12),
                            ),
                          ],
                        ],
                      ),
                    ),
                    StatusPill(label: state.replaceAll('_', ' '), color: color),
                  ],
                ),
              );
            },
          ),
      ],
    );
  }
}

class ReleasesPage extends StatelessWidget {
  const ReleasesPage({super.key, required this.data});
  final Map<String, dynamic> data;

  @override
  Widget build(BuildContext context) {
    final releases = map(data['releases']);
    final counts = map(releases['counts']);
    final videos = listOf(releases['videos']);
    final metaReleases = listOf(releases['meta']);
    final metaQueue = map(releases['meta_queue']);
    final facebook = map(metaQueue['facebook']);
    final instagram = map(metaQueue['instagram']);
    return PageList(
      children: [
        const PageTitle(
          title: 'Release board',
          subtitle:
              'YouTube, Facebook and Instagram truth, queues and safe publishing state',
        ),
        MetricGrid(
          metrics: [
            for (final entry in counts.entries)
              Metric(
                entry.key.replaceAll('_', ' '),
                entry.value,
                Icons.play_circle_fill_rounded,
                statusColor(entry.key),
              ),
          ],
        ),
        MetricGrid(
          metrics: [
            Metric(
              'Facebook queued',
              facebook['queued'] ?? 0,
              Icons.facebook_rounded,
              _cyan,
            ),
            Metric(
              'Facebook published',
              facebook['published'] ?? 0,
              Icons.public_rounded,
              _green,
            ),
            Metric(
              'Instagram queued',
              instagram['queued'] ?? 0,
              Icons.camera_alt_rounded,
              _pink,
            ),
            Metric(
              'Instagram published',
              instagram['published'] ?? 0,
              Icons.public_rounded,
              _violet,
            ),
          ],
        ),
        const SectionTitle('YouTube releases'),
        for (final raw in videos)
          Builder(
            builder: (_) {
              final item = map(raw);
              final privacy = textOf(
                item['privacy_status'] ?? item['privacy'] ?? item['state'],
              );
              return SoftPanel(
                color: statusColor(privacy),
                child: Row(
                  children: [
                    Icon(
                      Icons.smart_display_rounded,
                      color: statusColor(privacy),
                      size: 34,
                    ),
                    const SizedBox(width: 14),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            textOf(item['title'], 'Untitled release'),
                            style: const TextStyle(fontWeight: FontWeight.w800),
                          ),
                          const SizedBox(height: 5),
                          Text(
                            textOf(
                              item['remote_publish_at'] ??
                                  item['publish_at'] ??
                                  item['published_at'] ??
                                  'Schedule pending',
                            ),
                            style: const TextStyle(color: _muted, fontSize: 12),
                          ),
                        ],
                      ),
                    ),
                    StatusPill(
                      label: privacy.isEmpty ? 'tracked' : privacy,
                      color: statusColor(privacy),
                    ),
                  ],
                ),
              );
            },
          ),
        const SectionTitle('Facebook & Instagram releases'),
        if (metaReleases.isEmpty)
          const EmptyState(
            'Future audited Meta releases are queued; none has reached its due time yet.',
          ),
        for (final raw in metaReleases)
          Builder(
            builder: (_) {
              final item = map(raw);
              final platform = textOf(item['platform'], 'meta');
              final state = textOf(item['status'], 'tracked');
              return SoftPanel(
                color: platform == 'instagram' ? _pink : _cyan,
                child: Row(
                  children: [
                    Icon(
                      platform == 'instagram'
                          ? Icons.camera_alt_rounded
                          : Icons.facebook_rounded,
                      color: platform == 'instagram' ? _pink : _cyan,
                      size: 32,
                    ),
                    const SizedBox(width: 14),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            '${platform.toUpperCase()} · ${textOf(item['series_id'])} Episode ${item['episode'] ?? '—'}',
                            style: const TextStyle(fontWeight: FontWeight.w800),
                          ),
                          Text(
                            textOf(
                              item['published_at'] ?? item['publish_at'],
                              'Awaiting due slot',
                            ),
                            style: const TextStyle(color: _muted, fontSize: 12),
                          ),
                        ],
                      ),
                    ),
                    StatusPill(
                      label: state.replaceAll('_', ' '),
                      color: statusColor(state),
                    ),
                  ],
                ),
              );
            },
          ),
      ],
    );
  }
}

class PerformancePage extends StatelessWidget {
  const PerformancePage({super.key, required this.data});
  final Map<String, dynamic> data;

  @override
  Widget build(BuildContext context) {
    final performance = map(data['performance']);
    final channel = map(performance['channel']);
    final episodes = listOf(performance['episodes']);
    final tags = listOf(performance['tag_performance']);
    final metaAnalytics = map(performance['meta_analytics']);
    final metaPlatforms = map(metaAnalytics['platforms']);
    final platformLearning = map(
      map(performance['platform_learning'])['platforms'],
    );
    return PageList(
      children: [
        const PageTitle(
          title: 'Performance intelligence',
          subtitle: 'Real evidence only—no invented retention',
        ),
        MetricGrid(
          metrics: [
            Metric(
              'Views',
              channel['channel_views'] ??
                  channel['views'] ??
                  channel['total_views'] ??
                  0,
              Icons.visibility_rounded,
              _violet,
            ),
            Metric(
              'Subscribers',
              channel['subscribers'] ?? channel['subscriber_count'] ?? 0,
              Icons.people_alt_rounded,
              _pink,
            ),
            Metric(
              'Watch time',
              channel['watch_time_hours'] ??
                  channel['estimated_minutes_watched'] ??
                  '—',
              Icons.timer_rounded,
              _cyan,
            ),
            Metric(
              'Videos',
              channel['videos'] ?? channel['video_count'] ?? episodes.length,
              Icons.video_library_rounded,
              _amber,
            ),
          ],
        ),
        const SectionTitle('Facebook & Instagram evidence'),
        for (final name in const ['facebook', 'instagram'])
          Builder(
            builder: (_) {
              final platform = map(metaPlatforms[name]);
              final learning = map(platformLearning[name]);
              final observations = listOf(learning['observations']);
              final meaningful = observations
                  .where((item) => map(item)['meaningful'] == true)
                  .length;
              return SoftPanel(
                color: name == 'instagram' ? _pink : _cyan,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Icon(
                          name == 'instagram'
                              ? Icons.camera_alt_rounded
                              : Icons.facebook_rounded,
                          color: name == 'instagram' ? _pink : _cyan,
                        ),
                        const SizedBox(width: 10),
                        Expanded(
                          child: Text(
                            name.toUpperCase(),
                            style: const TextStyle(fontWeight: FontWeight.w900),
                          ),
                        ),
                        StatusPill(
                          label: textOf(platform['status'], 'waiting'),
                          color: statusColor(textOf(platform['status'])),
                        ),
                      ],
                    ),
                    const SizedBox(height: 12),
                    Wrap(
                      spacing: 14,
                      runSpacing: 7,
                      children: [
                        MiniStat('Views', platform['views'] ?? 0),
                        MiniStat('Likes', platform['likes'] ?? 0),
                        MiniStat('Comments', platform['comments'] ?? 0),
                        MiniStat('Shares', platform['shares'] ?? 0),
                        MiniStat('Learning samples', meaningful),
                      ],
                    ),
                    const SizedBox(height: 8),
                    const Text(
                      'Independent 24h / 72h / 168h evidence; unavailable metrics remain unknown.',
                      style: TextStyle(color: _muted, fontSize: 11),
                    ),
                  ],
                ),
              );
            },
          ),
        const SectionTitle('Episode performance'),
        if (episodes.isEmpty)
          const EmptyState('Waiting for eligible organic data.'),
        for (final raw in episodes)
          Builder(
            builder: (_) {
              final item = map(raw);
              final itemTags = listOf(item['tags'])
                  .take(4)
                  .map((value) => textOf(value))
                  .where((value) => value.isNotEmpty);
              return SoftPanel(
                color: _cyan,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      textOf(
                        item['title'] ?? item['episode_title'],
                        'Tracked episode',
                      ),
                      style: const TextStyle(fontWeight: FontWeight.w800),
                    ),
                    const SizedBox(height: 9),
                    Wrap(
                      spacing: 14,
                      runSpacing: 7,
                      children: [
                        MiniStat('Views', item['views'] ?? 0),
                        MiniStat('Engaged', item['engaged_views'] ?? '—'),
                        MiniStat('Shorts Feed', item['shorts_feed_views'] ?? 0),
                        MiniStat(
                          'Distribution',
                          textOf(item['organic_distribution_status'], 'waiting')
                              .replaceAll('_', ' '),
                        ),
                        MiniStat(
                          'Avg %',
                          item['average_view_percentage'] ?? '—',
                        ),
                        MiniStat(
                          'Learning',
                          textOf(
                            item['learning_eligibility'],
                            'waiting',
                          ).replaceAll('_', ' '),
                        ),
                      ],
                    ),
                    if (itemTags.isNotEmpty) ...[
                      const SizedBox(height: 10),
                      Wrap(
                        spacing: 6,
                        runSpacing: 6,
                        children: [for (final tag in itemTags) SmallChip(tag)],
                      ),
                    ],
                  ],
                ),
              );
            },
          ),
        const SectionTitle('Tag signals'),
        if (tags.isEmpty)
          const EmptyState(
            'Tag confidence is waiting for enough organic evidence.',
          ),
        for (final raw in tags.take(30))
          Builder(
            builder: (_) {
              final item = map(raw);
              return SoftPanel(
                child: Row(
                  children: [
                    const Icon(Icons.tag_rounded, color: _pink),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Text(
                        textOf(item['tag'] ?? item['name']),
                        style: const TextStyle(fontWeight: FontWeight.w700),
                      ),
                    ),
                    Text(
                      textOf(item['confidence'] ?? item['score'] ?? 'learning'),
                      style: const TextStyle(color: _muted),
                    ),
                  ],
                ),
              );
            },
          ),
      ],
    );
  }
}

class SystemPage extends StatelessWidget {
  const SystemPage({super.key, required this.data});
  final Map<String, dynamic> data;

  @override
  Widget build(BuildContext context) {
    final system = map(data['system']);
    final access = map(data['access']);
    final platforms = map(system['platforms']);
    final sections = <(String, IconData, Color, Map<String, dynamic>)>[
      ('Scheduler', Icons.schedule_rounded, _violet, map(system['scheduler'])),
      (
        'Supervisor',
        Icons.health_and_safety_rounded,
        _green,
        map(system['supervisor']),
      ),
      (
        'Certification',
        Icons.verified_user_rounded,
        _cyan,
        map(system['certification']),
      ),
      ('Backup', Icons.cloud_done_rounded, _pink, map(system['backup'])),
      (
        'Meta scheduler',
        Icons.sync_rounded,
        _cyan,
        map(system['meta_scheduler']),
      ),
      (
        'YouTube platform',
        Icons.smart_display_rounded,
        _red,
        map(platforms['youtube']),
      ),
      (
        'Facebook platform',
        Icons.facebook_rounded,
        _cyan,
        map(platforms['facebook']),
      ),
      (
        'Instagram platform',
        Icons.camera_alt_rounded,
        _pink,
        map(platforms['instagram']),
      ),
      (
        'Production gate',
        Icons.lock_clock_rounded,
        _amber,
        map(system['production_gate']),
      ),
    ];
    return PageList(
      children: [
        const PageTitle(
          title: 'System integrity',
          subtitle: 'Recovery, certification and fail-closed safeguards',
        ),
        SoftPanel(
          color: _green,
          child: Row(
            children: [
              const Icon(Icons.lock_rounded, color: _green, size: 32),
              const SizedBox(width: 14),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      'Secure access',
                      style: TextStyle(fontWeight: FontWeight.w900),
                    ),
                    Text(
                      '${textOf(access['mode'], Platform.isWindows ? 'local_control' : 'remote_read_only')} · ${textOf(access['public_hostname'], 'yt.kaapav.com')}',
                      style: const TextStyle(color: _muted),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
        for (final section in sections)
          SoftPanel(
            color: section.$3,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                SectionLabel(
                  icon: section.$2,
                  title: section.$1,
                  color: section.$3,
                ),
                const SizedBox(height: 12),
                if (section.$4.isEmpty)
                  const Text(
                    'No status reported',
                    style: TextStyle(color: _muted),
                  ),
                for (final entry in section.$4.entries.take(10))
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 4),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Expanded(
                          child: Text(
                            entry.key.replaceAll('_', ' '),
                            style: const TextStyle(color: _muted),
                          ),
                        ),
                        const SizedBox(width: 12),
                        Flexible(
                          child: Text(
                            compact(entry.value),
                            textAlign: TextAlign.right,
                            style: const TextStyle(fontWeight: FontWeight.w700),
                          ),
                        ),
                      ],
                    ),
                  ),
              ],
            ),
          ),
      ],
    );
  }
}

class PairingView extends StatefulWidget {
  const PairingView({super.key, required this.api, required this.onPaired});
  final DashboardApi api;
  final Future<void> Function() onPaired;

  @override
  State<PairingView> createState() => _PairingViewState();
}

class _PairingViewState extends State<PairingView> {
  final code = TextEditingController();
  String? message;
  bool busy = false;

  @override
  void dispose() {
    code.dispose();
    super.dispose();
  }

  Future<void> pair() async {
    setState(() {
      busy = true;
      message = null;
    });
    try {
      await widget.api.pair(code.text);
      await widget.onPaired();
    } catch (caught) {
      if (mounted) setState(() => message = '$caught');
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(24),
      children: [
        const SizedBox(height: 40),
        Center(
          child: SizedBox(
            width: 560,
            child: SoftPanel(
              color: _violet,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Icon(
                    Icons.phonelink_lock_rounded,
                    size: 52,
                    color: _violet,
                  ),
                  const SizedBox(height: 18),
                  const Text(
                    'Pair this device',
                    style: TextStyle(fontSize: 26, fontWeight: FontWeight.w900),
                  ),
                  const SizedBox(height: 8),
                  const Text(
                    'On the authorized studio PC, open the KAAPAV app-pairing shortcut. Enter its single-use 60-second code here. Pairing is needed only when the signed session expires.',
                    style: TextStyle(color: _muted, height: 1.45),
                  ),
                  const SizedBox(height: 18),
                  TextField(
                    controller: code,
                    autocorrect: false,
                    decoration: const InputDecoration(
                      labelText: 'One-time pairing code',
                      filled: true,
                      fillColor: Color(0xFFF3F7FC),
                      border: OutlineInputBorder(
                        borderRadius: BorderRadius.all(Radius.circular(16)),
                      ),
                    ),
                  ),
                  if (message != null)
                    Padding(
                      padding: const EdgeInsets.only(top: 10),
                      child: Text(
                        message!,
                        style: const TextStyle(color: _red),
                      ),
                    ),
                  const SizedBox(height: 16),
                  SizedBox(
                    width: double.infinity,
                    child: FilledButton.icon(
                      onPressed: busy ? null : pair,
                      icon: const Icon(Icons.link_rounded),
                      label: Text(busy ? 'Pairing…' : 'Pair securely'),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ],
    );
  }
}

class PageList extends StatelessWidget {
  const PageList({super.key, required this.children});
  final List<Widget> children;

  @override
  Widget build(BuildContext context) => ListView(
    padding: const EdgeInsets.fromLTRB(22, 12, 22, 40),
    children: children,
  );
}

class PageTitle extends StatelessWidget {
  const PageTitle({super.key, required this.title, required this.subtitle});
  final String title;
  final String subtitle;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(bottom: 18),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          title,
          style: const TextStyle(
            fontSize: 28,
            fontWeight: FontWeight.w900,
            letterSpacing: -.6,
          ),
        ),
        const SizedBox(height: 4),
        Text(subtitle, style: const TextStyle(color: _muted)),
      ],
    ),
  );
}

class SectionTitle extends StatelessWidget {
  const SectionTitle(this.label, {super.key});
  final String label;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.fromLTRB(4, 20, 4, 10),
    child: Text(
      label.toUpperCase(),
      style: const TextStyle(
        color: _muted,
        fontSize: 12,
        fontWeight: FontWeight.w900,
        letterSpacing: 1.2,
      ),
    ),
  );
}

class SoftPanel extends StatelessWidget {
  const SoftPanel({super.key, required this.child, this.color});
  final Widget child;
  final Color? color;

  @override
  Widget build(BuildContext context) => Container(
    margin: const EdgeInsets.only(bottom: 14),
    padding: const EdgeInsets.all(18),
    decoration: softDecoration(radius: 22, accent: color),
    child: child,
  );
}

class Metric {
  const Metric(this.label, this.value, this.icon, this.color);
  final String label;
  final Object? value;
  final IconData icon;
  final Color color;
}

class MetricGrid extends StatelessWidget {
  const MetricGrid({super.key, required this.metrics});
  final List<Metric> metrics;

  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, box) {
      final count = box.maxWidth >= 1050
          ? 3
          : box.maxWidth >= 580
          ? 2
          : 1;
      final width = (box.maxWidth - (count - 1) * 14) / count;
      return Wrap(
        spacing: 14,
        runSpacing: 14,
        children: [
          for (final metric in metrics)
            SizedBox(
              width: width,
              child: Container(
                padding: const EdgeInsets.all(18),
                decoration: softDecoration(radius: 22, accent: metric.color),
                child: Row(
                  children: [
                    Container(
                      width: 46,
                      height: 46,
                      decoration: BoxDecoration(
                        color: metric.color.withValues(alpha: .13),
                        borderRadius: BorderRadius.circular(15),
                      ),
                      child: Icon(metric.icon, color: metric.color),
                    ),
                    const SizedBox(width: 13),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            compact(metric.value),
                            style: const TextStyle(
                              fontSize: 22,
                              fontWeight: FontWeight.w900,
                            ),
                          ),
                          Text(
                            metric.label,
                            style: const TextStyle(color: _muted, fontSize: 12),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
            ),
        ],
      );
    },
  );
}

class SectionLabel extends StatelessWidget {
  const SectionLabel({
    super.key,
    required this.icon,
    required this.title,
    required this.color,
  });
  final IconData icon;
  final String title;
  final Color color;

  @override
  Widget build(BuildContext context) => Row(
    children: [
      Icon(icon, color: color),
      const SizedBox(width: 9),
      Text(
        title,
        style: const TextStyle(fontWeight: FontWeight.w900, fontSize: 16),
      ),
    ],
  );
}

class StatusPill extends StatelessWidget {
  const StatusPill({super.key, required this.label, required this.color});
  final String label;
  final Color color;

  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 7),
    decoration: BoxDecoration(
      color: color.withValues(alpha: .14),
      borderRadius: BorderRadius.circular(99),
    ),
    child: Text(
      label.toUpperCase(),
      style: TextStyle(
        color: color,
        fontSize: 10,
        fontWeight: FontWeight.w900,
        letterSpacing: .5,
      ),
    ),
  );
}

class SmallChip extends StatelessWidget {
  const SmallChip(this.label, {super.key});
  final String label;

  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 5),
    decoration: BoxDecoration(
      color: _pink.withValues(alpha: .1),
      borderRadius: BorderRadius.circular(20),
    ),
    child: Text(
      label,
      style: const TextStyle(
        color: _pink,
        fontSize: 10,
        fontWeight: FontWeight.w700,
      ),
    ),
  );
}

class MiniStat extends StatelessWidget {
  const MiniStat(this.label, this.value, {super.key});
  final String label;
  final Object? value;

  @override
  Widget build(BuildContext context) => Text(
    '$label  ${compact(value)}',
    style: const TextStyle(
      color: _muted,
      fontSize: 12,
      fontWeight: FontWeight.w700,
    ),
  );
}

class NavButton extends StatelessWidget {
  const NavButton({
    super.key,
    required this.icon,
    required this.label,
    required this.color,
    required this.selected,
    required this.onTap,
  });
  final IconData icon;
  final String label;
  final Color color;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => Tooltip(
    message: label,
    child: InkWell(
      borderRadius: BorderRadius.circular(18),
      onTap: onTap,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 180),
        width: 62,
        height: 58,
        decoration: selected ? pressedDecoration(color) : null,
        child: Icon(icon, color: selected ? color : _muted),
      ),
    ),
  );
}

class SoftIconButton extends StatelessWidget {
  const SoftIconButton({super.key, required this.icon, required this.onTap});
  final IconData icon;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => InkWell(
    borderRadius: BorderRadius.circular(14),
    onTap: onTap,
    child: Container(
      width: 40,
      height: 40,
      decoration: softDecoration(radius: 14),
      child: Icon(icon, color: _violet, size: 20),
    ),
  );
}

class EmptyState extends StatelessWidget {
  const EmptyState(this.message, {super.key});
  final String message;

  @override
  Widget build(BuildContext context) => SoftPanel(
    child: Row(
      children: [
        const Icon(Icons.hourglass_empty_rounded, color: _muted),
        const SizedBox(width: 12),
        Expanded(
          child: Text(message, style: const TextStyle(color: _muted)),
        ),
      ],
    ),
  );
}

class ErrorView extends StatelessWidget {
  const ErrorView({super.key, required this.message, required this.onRetry});
  final String message;
  final Future<void> Function() onRetry;

  @override
  Widget build(BuildContext context) => Center(
    child: Padding(
      padding: const EdgeInsets.all(24),
      child: SoftPanel(
        color: _red,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.cloud_off_rounded, color: _red, size: 46),
            const SizedBox(height: 12),
            const Text(
              'Dashboard unavailable',
              style: TextStyle(fontWeight: FontWeight.w900, fontSize: 20),
            ),
            const SizedBox(height: 6),
            Text(
              message,
              textAlign: TextAlign.center,
              style: const TextStyle(color: _muted),
            ),
            const SizedBox(height: 16),
            FilledButton.icon(
              onPressed: onRetry,
              icon: const Icon(Icons.refresh_rounded),
              label: const Text('Retry'),
            ),
          ],
        ),
      ),
    ),
  );
}

BoxDecoration softDecoration({
  double radius = 20,
  Color? accent,
}) => BoxDecoration(
  color: _bg,
  borderRadius: BorderRadius.circular(radius),
  border: accent == null
      ? null
      : Border(left: BorderSide(color: accent, width: 4)),
  boxShadow: const [
    BoxShadow(color: Color(0xFFFFFFFF), blurRadius: 14, offset: Offset(-6, -6)),
    BoxShadow(color: Color(0xFFBCC8DB), blurRadius: 16, offset: Offset(7, 7)),
  ],
);

BoxDecoration pressedDecoration(Color color) => BoxDecoration(
  color: const Color(0xFFDDE5F1),
  borderRadius: BorderRadius.circular(18),
  border: Border.all(color: color.withValues(alpha: .22)),
  boxShadow: const [
    BoxShadow(
      color: Color(0x70B5C1D4),
      blurRadius: 6,
      offset: Offset(3, 3),
      blurStyle: BlurStyle.inner,
    ),
    BoxShadow(
      color: Color(0xCFFFFFFF),
      blurRadius: 5,
      offset: Offset(-3, -3),
      blurStyle: BlurStyle.inner,
    ),
  ],
);

Map<String, dynamic> map(Object? value) =>
    value is Map<String, dynamic> ? value : <String, dynamic>{};
List<dynamic> listOf(Object? value) => value is List ? value : const [];
String textOf(Object? value, [String fallback = '']) =>
    value == null || '$value'.isEmpty ? fallback : '$value';
double numberOf(Object? value) =>
    value is num ? value.toDouble() : double.tryParse('$value') ?? 0;

String compact(Object? value) {
  if (value is Map || value is List) {
    return jsonEncode(value);
  }
  if (value is double) {
    return value.toStringAsFixed(value.truncateToDouble() == value ? 0 : 1);
  }
  return textOf(value, '—');
}

Color statusColor(String value) {
  final key = value.toLowerCase();
  if (key.contains('public') ||
      key.contains('ready') ||
      key.contains('pass') ||
      key.contains('ok')) {
    return _green;
  }
  if (key.contains('schedule') ||
      key.contains('progress') ||
      key.contains('render')) {
    return _cyan;
  }
  if (key.contains('pause') ||
      key.contains('pending') ||
      key.contains('private')) {
    return _amber;
  }
  if (key.contains('fail') || key.contains('block') || key.contains('error')) {
    return _red;
  }
  if (key.contains('image')) {
    return _pink;
  }
  return _violet;
}
