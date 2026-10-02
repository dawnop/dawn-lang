cuda_tile.module @m {
  entry @loop_return(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<i32>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = constant <i32: 256> : tile<i32>
    %7 = muli %1, %6 : tile<i32>
    %8 = constant <i32: 1> : tile<128xi32>
    %9 = reshape %5 : tile<i32> -> tile<1xi32>
    %10 = broadcast %9 : tile<1xi32> -> tile<128xi32>
    %11 = iota : tile<128xi32>
    %12 = addi %10, %11 : tile<128xi32>
    %13 = reshape %arg0 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %14 = broadcast %13 : tile<1xptr<i32>> -> tile<128xptr<i32>>
    %15 = offset %14, %12 : tile<128xptr<i32>>, tile<128xi32> -> tile<128xptr<i32>>
    %16, %17 = load_ptr_tko weak %15 token=%0 : tile<128xptr<i32>> -> tile<128xi32>, token
    %18 = constant <i32: 0> : tile<128xi32>
    %19, %20, %21 = loop iter_values(%22 = %16, %23 = %18, %24 = %17) : tile<128xi32>, tile<128xi32>, token -> (tile<128xi32>, tile<128xi32>, token) {
      %25 = addi %23, %8 : tile<128xi32>
      %26 = reshape %7 : tile<i32> -> tile<1xi32>
      %27 = broadcast %26 : tile<1xi32> -> tile<128xi32>
      %28 = iota : tile<128xi32>
      %29 = addi %27, %28 : tile<128xi32>
      %30 = reshape %arg1 : tile<ptr<i32>> -> tile<1xptr<i32>>
      %31 = broadcast %30 : tile<1xptr<i32>> -> tile<128xptr<i32>>
      %32 = offset %31, %29 : tile<128xptr<i32>>, tile<128xi32> -> tile<128xptr<i32>>
      %33 = store_ptr_tko weak %32, %25 token=%24 : tile<128xptr<i32>>, tile<128xi32> -> token
      %34 = reduce %22 dim=0 identities=[0 : i32] : tile<128xi32> -> tile<i32> (%35: tile<i32>, %36: tile<i32>) {
        %37 = maxi %35, %36 signed : tile<i32>
        yield %37 : tile<i32>
      }
      %38 = constant <i32: 200> : tile<i32>
      %39 = cmpi less_than_or_equal %38, %34, signed : tile<i32> -> tile<i1>
      if %39 {
        return
      } else {
        yield
      }
      %40 = reduce %25 dim=0 identities=[0 : i32] : tile<128xi32> -> tile<i32> (%41: tile<i32>, %42: tile<i32>) {
        %43 = maxi %41, %42 signed : tile<i32>
        yield %43 : tile<i32>
      }
      %44 = constant <i32: 100> : tile<i32>
      %45 = cmpi less_than_or_equal %44, %40, signed : tile<i32> -> tile<i1>
      %46 = addi %22, %8 : tile<128xi32>
      if %45 {
        break %22, %23, %33 : tile<128xi32>, tile<128xi32>, token
      } else {
        yield
      }
      continue %46, %25, %33 : tile<128xi32>, tile<128xi32>, token
    }
    %47 = constant <i32: 128> : tile<i32>
    %48 = addi %7, %47 : tile<i32>
    %49 = reshape %48 : tile<i32> -> tile<1xi32>
    %50 = broadcast %49 : tile<1xi32> -> tile<128xi32>
    %51 = iota : tile<128xi32>
    %52 = addi %50, %51 : tile<128xi32>
    %53 = reshape %arg1 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %54 = broadcast %53 : tile<1xptr<i32>> -> tile<128xptr<i32>>
    %55 = offset %54, %52 : tile<128xptr<i32>>, tile<128xi32> -> tile<128xptr<i32>>
    %56 = store_ptr_tko weak %55, %19 token=%21 : tile<128xptr<i32>>, tile<128xi32> -> token
    return
  }
}
