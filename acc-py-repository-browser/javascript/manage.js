function show_page(page_class){
    $('a[data-purpose="page-select"]').addClass('btn-link').removeClass('btn-primary')
    $('a[data-purpose="page-select"].' + page_class).addClass('btn-primary').removeClass('btn-link')

    $('div[data-purpose="page-switch"]').addClass('d-none');
    $('#' + page_class + '-page').removeClass('d-none').removeClass('d-none').removeClass('d-none');
}

$('a.releases').click(() => {
    show_page('releases');
    const currentUrlWithoutFragment = window.location.href.split('#')[0];

    history.replaceState({}, 'Releases', currentUrlWithoutFragment + "#releases");
  }
)

$('a.not-implemented').click(() => {alert("This feature is not implemented yet!")})
$('button.not-implemented').click(() => {alert("This feature is not implemented yet!")})

show_page("releases");
