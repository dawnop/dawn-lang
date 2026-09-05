cuda_tile.module @m {
  entry @print_tile(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<i32>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = reshape %5 : tile<i32> -> tile<1xi32>
    %7 = broadcast %6 : tile<1xi32> -> tile<128xi32>
    %8 = iota : tile<128xi32>
    %9 = addi %7, %8 : tile<128xi32>
    %10 = reshape %arg0 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %11 = broadcast %10 : tile<1xptr<i32>> -> tile<128xptr<i32>>
    %12 = offset %11, %9 : tile<128xptr<i32>>, tile<128xi32> -> tile<128xptr<i32>>
    %13, %14 = load_ptr_tko weak %12 token=%0 : tile<128xptr<i32>> -> tile<128xi32>, token
    %15 = reduce %13 dim=0 identities=[0 : i32] : tile<128xi32> -> tile<i32> (%16: tile<i32>, %17: tile<i32>) {
      %18 = addi %16, %17 : tile<i32>
      yield %18 : tile<i32>
    }
    %19 = reduce %13 dim=0 identities=[0 : i32] : tile<128xi32> -> tile<i32> (%20: tile<i32>, %21: tile<i32>) {
      %22 = maxi %20, %21 signed : tile<i32>
      yield %22 : tile<i32>
    }
    %23 = print_tko "print_tile sum=%d max=%d\n", %15, %19 token=%14 : tile<i32>, tile<i32> -> token
    %24 = reshape %arg1 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %25 = broadcast %24 : tile<1xptr<i32>> -> tile<128xptr<i32>>
    %26 = offset %25, %9 : tile<128xptr<i32>>, tile<128xi32> -> tile<128xptr<i32>>
    %27 = store_ptr_tko weak %26, %13 token=%23 : tile<128xptr<i32>>, tile<128xi32> -> token
    %28 = constant <i32: 1> : tile<i32>
    %29 = constant <i32: 128> : tile<i32>
    %30 = muli %28, %29 : tile<i32>
    %31 = reshape %15 : tile<i32> -> tile<1xi32>
    %32 = broadcast %31 : tile<1xi32> -> tile<128xi32>
    %33 = reshape %30 : tile<i32> -> tile<1xi32>
    %34 = broadcast %33 : tile<1xi32> -> tile<128xi32>
    %35 = iota : tile<128xi32>
    %36 = addi %34, %35 : tile<128xi32>
    %37 = reshape %arg1 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %38 = broadcast %37 : tile<1xptr<i32>> -> tile<128xptr<i32>>
    %39 = offset %38, %36 : tile<128xptr<i32>>, tile<128xi32> -> tile<128xptr<i32>>
    %40 = store_ptr_tko weak %39, %32 token=%27 : tile<128xptr<i32>>, tile<128xi32> -> token
    %41 = constant <i32: 2> : tile<i32>
    %42 = constant <i32: 128> : tile<i32>
    %43 = muli %41, %42 : tile<i32>
    %44 = reshape %19 : tile<i32> -> tile<1xi32>
    %45 = broadcast %44 : tile<1xi32> -> tile<128xi32>
    %46 = reshape %43 : tile<i32> -> tile<1xi32>
    %47 = broadcast %46 : tile<1xi32> -> tile<128xi32>
    %48 = iota : tile<128xi32>
    %49 = addi %47, %48 : tile<128xi32>
    %50 = reshape %arg1 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %51 = broadcast %50 : tile<1xptr<i32>> -> tile<128xptr<i32>>
    %52 = offset %51, %49 : tile<128xptr<i32>>, tile<128xi32> -> tile<128xptr<i32>>
    %53 = store_ptr_tko weak %52, %45 token=%40 : tile<128xptr<i32>>, tile<128xi32> -> token
    return
  }
}
