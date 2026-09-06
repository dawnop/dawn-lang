cuda_tile.module @m {
  entry @pack_roundtrip(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<i32>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 32> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = reshape %5 : tile<i32> -> tile<1xi32>
    %7 = broadcast %6 : tile<1xi32> -> tile<32xi32>
    %8 = iota : tile<32xi32>
    %9 = addi %7, %8 : tile<32xi32>
    %10 = reshape %arg0 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %11 = broadcast %10 : tile<1xptr<i32>> -> tile<32xptr<i32>>
    %12 = offset %11, %9 : tile<32xptr<i32>>, tile<32xi32> -> tile<32xptr<i32>>
    %13, %14 = load_ptr_tko weak %12 token=%0 : tile<32xptr<i32>> -> tile<32xi32>, token
    %15 = pack %13 : tile<32xi32> -> tile<128xi8>
    %16 = constant <i32: 0> : tile<i32>
    %17 = addi %5, %16 : tile<i32>
    %18 = unpack %15 : tile<128xi8> -> tile<256xi4>
    %19 = pack %18 : tile<256xi4> -> tile<128xi8>
    %20 = unpack %19 : tile<128xi8> -> tile<32xi32>
    %21 = reshape %17 : tile<i32> -> tile<1xi32>
    %22 = broadcast %21 : tile<1xi32> -> tile<32xi32>
    %23 = iota : tile<32xi32>
    %24 = addi %22, %23 : tile<32xi32>
    %25 = reshape %arg1 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %26 = broadcast %25 : tile<1xptr<i32>> -> tile<32xptr<i32>>
    %27 = offset %26, %24 : tile<32xptr<i32>>, tile<32xi32> -> tile<32xptr<i32>>
    %28 = store_ptr_tko weak %27, %20 token=%14 : tile<32xptr<i32>>, tile<32xi32> -> token
    %29 = constant <i32: 512> : tile<i32>
    %30 = addi %5, %29 : tile<i32>
    %31 = unpack %15 : tile<128xi8> -> tile<64xi16>
    %32 = pack %31 : tile<64xi16> -> tile<128xi8>
    %33 = unpack %32 : tile<128xi8> -> tile<32xi32>
    %34 = reshape %30 : tile<i32> -> tile<1xi32>
    %35 = broadcast %34 : tile<1xi32> -> tile<32xi32>
    %36 = iota : tile<32xi32>
    %37 = addi %35, %36 : tile<32xi32>
    %38 = reshape %arg1 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %39 = broadcast %38 : tile<1xptr<i32>> -> tile<32xptr<i32>>
    %40 = offset %39, %37 : tile<32xptr<i32>>, tile<32xi32> -> tile<32xptr<i32>>
    %41 = store_ptr_tko weak %40, %33 token=%28 : tile<32xptr<i32>>, tile<32xi32> -> token
    return
  }
}
