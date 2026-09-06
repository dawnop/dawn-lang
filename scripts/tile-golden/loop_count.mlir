cuda_tile.module @m {
  entry @loop_count(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<i32>>) {
    %0 = make_token : token
    %1 = constant <i32: 0> : tile<i32>
    %2 = constant <i32: 128> : tile<i32>
    %3 = muli %1, %2 : tile<i32>
    %4 = reshape %3 : tile<i32> -> tile<1xi32>
    %5 = broadcast %4 : tile<1xi32> -> tile<128xi32>
    %6 = iota : tile<128xi32>
    %7 = addi %5, %6 : tile<128xi32>
    %8 = reshape %arg0 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %9 = broadcast %8 : tile<1xptr<i32>> -> tile<128xptr<i32>>
    %10 = offset %9, %7 : tile<128xptr<i32>>, tile<128xi32> -> tile<128xptr<i32>>
    %11, %12 = load_ptr_tko weak %10 token=%0 : tile<128xptr<i32>> -> tile<128xi32>, token
    %13 = constant <i32: 0> : tile<128xi32>
    %14, %15, %16 = loop iter_values(%17 = %11, %18 = %13, %19 = %12) : tile<128xi32>, tile<128xi32>, token -> (tile<128xi32>, tile<128xi32>, token) {
      %20 = reduce %17 dim=0 identities=[1 : i32] : tile<128xi32> -> tile<i32> (%21: tile<i32>, %22: tile<i32>) {
        %23 = maxi %21, %22 signed : tile<i32>
        yield %23 : tile<i32>
      }
      %24 = constant <i32: 1> : tile<i32>
      %25 = cmpi less_than_or_equal %20, %24, signed : tile<i32> -> tile<i1>
      %26 = constant <i32: 1> : tile<128xi32>
      %27 = constant <i32: 2> : tile<128xi32>
      %28 = constant <i32: 3> : tile<128xi32>
      %29 = constant <i32: 0> : tile<128xi32>
      %30 = cmpi less_than %26, %17, signed : tile<128xi32> -> tile<128xi1>
      %31 = remi %17, %27 signed : tile<128xi32>
      %32 = cmpi equal %31, %29, signed : tile<128xi32> -> tile<128xi1>
      %33 = divi %17, %27 signed : tile<128xi32>
      %34 = muli %17, %28 : tile<128xi32>
      %35 = addi %34, %26 : tile<128xi32>
      %36 = select %32, %33, %35 : tile<128xi1>, tile<128xi32>
      %37 = select %30, %36, %17 : tile<128xi1>, tile<128xi32>
      %38 = select %30, %26, %29 : tile<128xi1>, tile<128xi32>
      %39 = addi %18, %38 : tile<128xi32>
      if %25 {
        break %17, %18, %19 : tile<128xi32>, tile<128xi32>, token
      } else {
        yield
      }
      continue %37, %39, %19 : tile<128xi32>, tile<128xi32>, token
    }
    %40 = reduce %15 dim=0 identities=[0 : i32] : tile<128xi32> -> tile<i32> (%41: tile<i32>, %42: tile<i32>) {
      %43 = maxi %41, %42 signed : tile<i32>
      yield %43 : tile<i32>
    }
    %44 = reshape %arg1 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %45 = broadcast %44 : tile<1xptr<i32>> -> tile<128xptr<i32>>
    %46 = offset %45, %7 : tile<128xptr<i32>>, tile<128xi32> -> tile<128xptr<i32>>
    %47 = store_ptr_tko weak %46, %15 token=%16 : tile<128xptr<i32>>, tile<128xi32> -> token
    %48 = constant <i32: 1> : tile<i32>
    %49 = constant <i32: 128> : tile<i32>
    %50 = muli %48, %49 : tile<i32>
    %51 = reshape %40 : tile<i32> -> tile<1xi32>
    %52 = broadcast %51 : tile<1xi32> -> tile<128xi32>
    %53 = reshape %50 : tile<i32> -> tile<1xi32>
    %54 = broadcast %53 : tile<1xi32> -> tile<128xi32>
    %55 = iota : tile<128xi32>
    %56 = addi %54, %55 : tile<128xi32>
    %57 = reshape %arg1 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %58 = broadcast %57 : tile<1xptr<i32>> -> tile<128xptr<i32>>
    %59 = offset %58, %56 : tile<128xptr<i32>>, tile<128xi32> -> tile<128xptr<i32>>
    %60 = store_ptr_tko weak %59, %52 token=%47 : tile<128xptr<i32>>, tile<128xi32> -> token
    return
  }
}
