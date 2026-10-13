# Status: Adapt first. kivitendo 4.0.1 with the reviewed EXTF-700/13 exporter.
# Run only through kivitendo scripts/console; see kivitendo-datev-handover.md.
# Reads accounting and document metadata in a repeatable, read-only transaction.
# Writes only into HANDOVER_STAGE; never posts, locks or marks bookings exported.
use strict;
use warnings;
use utf8;
use JSON::PP;
use DateTime;
use Digest::SHA qw(sha256_hex);
use Encode qw(encode);
use File::Path qw(make_path);
use SL::DATEV qw(:CONSTANTS);
use SL::DATEV::Profile;
use SL::DB::Manager::File;
use SL::DB::Manager::FileVersion;

my $j = JSON::PP->new->canonical->pretty;
my $cfg = $j->decode($ENV{HANDOVER_CONFIG_JSON} // die 'Missing configuration');
my $stage = $ENV{HANDOVER_STAGE} // die 'Missing staging directory';
my $dbh = SL::DB->client->dbh;
die 'Wrong client' unless $::auth->client->{id} == $cfg->{client_id};
die 'Wrong database' unless $dbh->selectrow_array('SELECT current_database()') eq $cfg->{database};
$dbh->begin_work;
$dbh->do('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY');
my $p = SL::DATEV::Profile->load;
for my $key (qw(consultant_number client_number)) {
  die "Profile mismatch: $key" unless "$p->{$key}" eq "$cfg->{$key}";
}
my @start = split /-/, $cfg->{start_date};
my @end = split /-/, $cfg->{as_of};
my $from = DateTime->new(year=>$start[0], month=>$start[1], day=>1);
my $asof = DateTime->new(year=>$end[0], month=>$end[1], day=>$end[2]);
my %report = (database=>$cfg->{database}, as_of=>$cfg->{as_of}, periods=>[], documents=>[], person_accounts=>[]);
my %objects;
while (DateTime->compare($from,$asof) <= 0) {
  my $to = $from->clone->add(months=>1)->subtract(days=>1);
  $to = $asof->clone if DateTime->compare($to,$asof)>0;
  my $period = $from->strftime('%Y-%m');
  my $dir = "$stage/periods/$period";
  make_path($dir);
  my $d = SL::DATEV->new(dbh=>$dbh, exporttype=>DATEV_ET_BUCHUNGEN,
    format=>DATEV_FORMAT_CSV, from=>$from->clone, to=>$to,
    use_pk=>1, imported=>1, locked=>0, documents=>1);
  # kivitendo's document ZIP writer expects a trailing slash.
  $d->{export_path} = "$dir/";
  $d->export;
  die join(';', $d->errors) if $d->errors;
  my $lines = $d->generate_datev_lines;
  my @unlinked;
  for my $line (@$lines) {
    my $source = $line->{source_table};
    my $id = $line->{source_trans_id};
    $objects{"$source:$id"}=1;
    if (!$line->{document_guid}) {
      die "Missing invoice PDF: $source:$id" if $source eq 'ar' || $source eq 'ap';
      push @unlinked, {source_table=>$source,source_id=>$id,reference=>$line->{belegfeld1}};
    }
  }
  push @{$report{periods}}, {period=>$period,from=>$d->from->ymd,to=>$to->ymd,
    rows=>scalar(@$lines),linked_rows=>scalar(grep {$_->{document_guid}} @$lines),
    unlinked_journal_rows=>\@unlinked,
    source_rows=>[map {{source_table=>$_->{source_table},source_id=>$_->{source_trans_id},
      reference=>$_->{belegfeld1},document_guid=>$_->{document_guid}//''}} @$lines]};
  $from->add(months=>1);
}
my %types=(invoice=>'ar',credit_note=>'ar',purchase_invoice=>'ap',gl_transaction=>'gl');
my $files=SL::DB::Manager::File->get_all(sort_by=>'id');
for my $file (@$files) {
  my $type=$types{$file->object_type} // next;
  next unless $objects{"$type:".$file->object_id};
  my $versions=$file->file_versions_sorted;
  die 'File without version' unless @$versions;
  my $v=$versions->[-1];
  push @{$report{documents}}, {guid=>$v->guid,path=>$v->get_system_location,
    name=>$file->file_name,mime_type=>$file->mime_type,file_type=>$file->file_type,
    source_table=>$type,source_id=>$file->object_id};
}
for my $spec (['customer','customernumber','Debitor'],['vendor','vendornumber','Kreditor']) {
  my ($table,$number,$label)=@$spec;
  my $rows=$dbh->selectall_arrayref("SELECT $number AS account, name FROM $table ORDER BY $number",{Slice=>{}});
  push @{$report{person_accounts}}, map {{%$_,type=>$label}} @$rows;
}
$report{journal_rows}=$dbh->selectrow_array('SELECT count(*) FROM acc_trans');
$report{accounting_fingerprints}={};
for my $table (qw(acc_trans ar ap gl datev defaults chart taxkeys customer vendor bank_transactions bank_transaction_acc_trans reconciliation_links)) {
  my $rows=$dbh->selectcol_arrayref("SELECT to_jsonb(t)::text FROM $table t ORDER BY to_jsonb(t)::text");
  $report{accounting_fingerprints}{$table}={count=>scalar(@$rows),sha256=>sha256_hex(encode('UTF-8',join("\n",@$rows)))};
}
$dbh->rollback;
open my $fh,'>:encoding(UTF-8)',"$stage/source.json" or die $!;
print $fh $j->encode(\%report); close $fh or die $!;
print "HANDOVER_EXTRACT_COMPLETE\n";
