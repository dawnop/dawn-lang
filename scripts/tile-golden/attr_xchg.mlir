cuda_tile.module @m {
  entry @attr_xchg(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<i32>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = constant <i32: 511> : tile<128xi32>
    %7 = reshape %5 : tile<i32> -> tile<1xi32>
    %8 = broadcast %7 : tile<1xi32> -> tile<128xi32>
    %9 = iota : tile<128xi32>
    %10 = addi %8, %9 : tile<128xi32>
    %11 = subi %6, %10 : tile<128xi32>
    %12 = reshape %arg0 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %13 = broadcast %12 : tile<1xptr<i32>> -> tile<128xptr<i32>>
    %14 = offset %13, %10 : tile<128xptr<i32>>, tile<128xi32> -> tile<128xptr<i32>>
    %15, %16 = load_ptr_tko weak %14 token=%0 : tile<128xptr<i32>> -> tile<128xi32>, token
    %17 = reshape %arg1 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %18 = broadcast %17 : tile<1xptr<i32>> -> tile<128xptr<i32>>
    %19 = offset %18, %11 : tile<128xptr<i32>>, tile<128xi32> -> tile<128xptr<i32>>
    %20, %21 = atomic_rmw_tko relaxed device %19, xchg, %15 token=%16 : tile<128xptr<i32>>, tile<128xi32> -> tile<128xi32>, token
    %22 = constant <i32: 512> : tile<i32>
    %23 = addi %5, %22 : tile<i32>
    %24 = reshape %23 : tile<i32> -> tile<1xi32>
    %25 = broadcast %24 : tile<1xi32> -> tile<128xi32>
    %26 = iota : tile<128xi32>
    %27 = addi %25, %26 : tile<128xi32>
    %28 = reshape %arg1 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %29 = broadcast %28 : tile<1xptr<i32>> -> tile<128xptr<i32>>
    %30 = offset %29, %27 : tile<128xptr<i32>>, tile<128xi32> -> tile<128xptr<i32>>
    %31 = store_ptr_tko weak %30, %20 token=%21 : tile<128xptr<i32>>, tile<128xi32> -> token
    return
  }
}
