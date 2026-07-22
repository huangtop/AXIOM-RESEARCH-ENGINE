<?php
/**
 * AXIOM read-only valuation dashboard adapter.
 * Python remains the only valuation source of truth.
 */

function axiom_valuation_api_base_url() {
    return untrailingslashit(
        apply_filters('axiom_valuation_api_base_url', 'http://127.0.0.1:8765')
    );
}

function axiom_register_valuation_assets() {
    $base = plugin_dir_url(__FILE__) . '../';
    wp_register_style(
        'axiom-valuation-dashboard',
        $base . 'axiom-valuation-dashboard.css',
        array(),
        '1.1.0'
    );
    wp_register_script(
        'axiom-valuation-dashboard',
        $base . 'axiom-valuation-dashboard.js',
        array(),
        '1.1.0',
        true
    );
}
add_action('wp_enqueue_scripts', 'axiom_register_valuation_assets');

function axiom_valuation_module_script($tag, $handle, $src) {
    if ($handle !== 'axiom-valuation-dashboard') {
        return $tag;
    }
    return '<script type="module" src="' . esc_url($src) . '"></script>';
}
add_filter('script_loader_tag', 'axiom_valuation_module_script', 10, 3);

function axiom_valuation_dashboard_shortcode($atts = array()) {
    $atts = shortcode_atts(
        array('ticker' => 'NVDA'),
        $atts,
        'axiom_valuation'
    );
    $ticker = strtoupper(sanitize_text_field($atts['ticker']));

    wp_enqueue_style('axiom-valuation-dashboard');
    wp_enqueue_script('axiom-valuation-dashboard');

    ob_start();
    ?>
    <div
        class="axiom-valuation-dashboard"
        data-axiom-dashboard
        data-api-base="<?php echo esc_attr(axiom_valuation_api_base_url()); ?>"
        data-initial-ticker="<?php echo esc_attr($ticker); ?>"
    >
        <div class="axiom-toolbar">
            <form data-axiom-form>
                <label>
                    Ticker
                    <input
                        data-axiom-ticker
                        name="ticker"
                        value="<?php echo esc_attr($ticker); ?>"
                        maxlength="16"
                        autocomplete="off"
                    >
                </label>
                <button type="submit">Run valuation</button>
            </form>
        </div>
        <div data-axiom-output aria-live="polite"></div>
    </div>
    <?php
    return ob_get_clean();
}
add_shortcode('axiom_valuation', 'axiom_valuation_dashboard_shortcode');
