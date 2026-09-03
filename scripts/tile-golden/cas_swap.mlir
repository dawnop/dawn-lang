cuda_tile.module @m {
  entry @cas_swap(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<i32>>, %arg2: tile<ptr<i32>>, %arg3: tile<ptr<i32>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 32> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = reshape %5 : tile<i32> -> tile<1xi32>
    %7 = broadcast %6 : tile<1xi32> -> tile<32xi32>
    %8 = iota : tile<32xi32>
    %9 = addi %7, %8 : tile<32xi32>
    %10 = reshape %arg1 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %11 = broadcast %10 : tile<1xptr<i32>> -> tile<32xptr<i32>>
    %12 = offset %11, %9 : tile<32xptr<i32>>, tile<32xi32> -> tile<32xptr<i32>>
    %13, %14 = load_ptr_tko weak %12 token=%0 : tile<32xptr<i32>> -> tile<32xi32>, token
    %15 = reshape %arg2 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %16 = broadcast %15 : tile<1xptr<i32>> -> tile<32xptr<i32>>
    %17 = offset %16, %9 : tile<32xptr<i32>>, tile<32xi32> -> tile<32xptr<i32>>
    %18, %19 = load_ptr_tko weak %17 token=%14 : tile<32xptr<i32>> -> tile<32xi32>, token
    %20 = constant <i32: 0> : tile<32xi32>
    %21 = cmpi greater_than_or_equal %13, %20, signed : tile<32xi32> -> tile<32xi1>
    %22 = reshape %arg0 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %23 = broadcast %22 : tile<1xptr<i32>> -> tile<32xptr<i32>>
    %24 = offset %23, %9 : tile<32xptr<i32>>, tile<32xi32> -> tile<32xptr<i32>>
    %25, %26 = atomic_cas_tko relaxed device %24, %13, %18, %21 token=%19 : tile<32xptr<i32>>, tile<32xi32>, tile<32xi1> -> tile<32xi32>, token
    %27 = reshape %arg3 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %28 = broadcast %27 : tile<1xptr<i32>> -> tile<32xptr<i32>>
    %29 = offset %28, %9 : tile<32xptr<i32>>, tile<32xi32> -> tile<32xptr<i32>>
    %30 = store_ptr_tko weak %29, %25, %21 token=%26 : tile<32xptr<i32>>, tile<32xi32>, tile<32xi1> -> token
    return
  }
}
