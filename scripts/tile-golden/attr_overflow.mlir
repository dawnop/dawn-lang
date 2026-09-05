cuda_tile.module @m {
  entry @attr_overflow(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<i32>>, %arg2: tile<ptr<i32>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = constant <i32: 384> : tile<i32>
    %7 = muli %1, %6 : tile<i32>
    %8 = reshape %5 : tile<i32> -> tile<1xi32>
    %9 = broadcast %8 : tile<1xi32> -> tile<128xi32>
    %10 = iota : tile<128xi32>
    %11 = addi %9, %10 : tile<128xi32>
    %12 = reshape %arg0 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %13 = broadcast %12 : tile<1xptr<i32>> -> tile<128xptr<i32>>
    %14 = offset %13, %11 : tile<128xptr<i32>>, tile<128xi32> -> tile<128xptr<i32>>
    %15, %16 = load_ptr_tko weak %14 token=%0 : tile<128xptr<i32>> -> tile<128xi32>, token
    %17 = reshape %arg1 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %18 = broadcast %17 : tile<1xptr<i32>> -> tile<128xptr<i32>>
    %19 = offset %18, %11 : tile<128xptr<i32>>, tile<128xi32> -> tile<128xptr<i32>>
    %20, %21 = load_ptr_tko weak %19 token=%16 : tile<128xptr<i32>> -> tile<128xi32>, token
    %22 = addi %15, %20 overflow<no_signed_wrap> : tile<128xi32>
    %23 = reshape %7 : tile<i32> -> tile<1xi32>
    %24 = broadcast %23 : tile<1xi32> -> tile<128xi32>
    %25 = iota : tile<128xi32>
    %26 = addi %24, %25 : tile<128xi32>
    %27 = reshape %arg2 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %28 = broadcast %27 : tile<1xptr<i32>> -> tile<128xptr<i32>>
    %29 = offset %28, %26 : tile<128xptr<i32>>, tile<128xi32> -> tile<128xptr<i32>>
    %30 = store_ptr_tko weak %29, %22 token=%21 : tile<128xptr<i32>>, tile<128xi32> -> token
    %31 = constant <i32: 128> : tile<i32>
    %32 = addi %7, %31 : tile<i32>
    %33 = subi %15, %20 overflow<no_unsigned_wrap> : tile<128xi32>
    %34 = reshape %32 : tile<i32> -> tile<1xi32>
    %35 = broadcast %34 : tile<1xi32> -> tile<128xi32>
    %36 = iota : tile<128xi32>
    %37 = addi %35, %36 : tile<128xi32>
    %38 = reshape %arg2 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %39 = broadcast %38 : tile<1xptr<i32>> -> tile<128xptr<i32>>
    %40 = offset %39, %37 : tile<128xptr<i32>>, tile<128xi32> -> tile<128xptr<i32>>
    %41 = store_ptr_tko weak %40, %33 token=%30 : tile<128xptr<i32>>, tile<128xi32> -> token
    %42 = constant <i32: 256> : tile<i32>
    %43 = addi %7, %42 : tile<i32>
    %44 = muli %15, %20 overflow<no_wrap> : tile<128xi32>
    %45 = reshape %43 : tile<i32> -> tile<1xi32>
    %46 = broadcast %45 : tile<1xi32> -> tile<128xi32>
    %47 = iota : tile<128xi32>
    %48 = addi %46, %47 : tile<128xi32>
    %49 = reshape %arg2 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %50 = broadcast %49 : tile<1xptr<i32>> -> tile<128xptr<i32>>
    %51 = offset %50, %48 : tile<128xptr<i32>>, tile<128xi32> -> tile<128xptr<i32>>
    %52 = store_ptr_tko weak %51, %44 token=%41 : tile<128xptr<i32>>, tile<128xi32> -> token
    return
  }
}
