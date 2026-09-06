cuda_tile.module @m {
  entry @loop_bound(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<i32>>) {
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
    %13 = constant <i32: 0> : tile<i32>
    %14 = constant <i32: 128> : tile<i32>
    %15 = constant <i32: 1> : tile<i32>
    %16 = constant <i32: 0> : tile<128xi32>
    %17, %18, %19 = for %20 in (%13 to %14, step %15) : tile<i32> iter_values(%21 = %11, %22 = %16, %23 = %12) -> (tile<128xi32>, tile<128xi32>, token) {
      %24 = constant <i32: 1> : tile<128xi32>
      %25 = constant <i32: 2> : tile<128xi32>
      %26 = constant <i32: 3> : tile<128xi32>
      %27 = constant <i32: 0> : tile<128xi32>
      %28 = cmpi less_than %24, %21, signed : tile<128xi32> -> tile<128xi1>
      %29 = remi %21, %25 signed : tile<128xi32>
      %30 = cmpi equal %29, %27, signed : tile<128xi32> -> tile<128xi1>
      %31 = divi %21, %25 signed : tile<128xi32>
      %32 = muli %21, %26 : tile<128xi32>
      %33 = addi %32, %24 : tile<128xi32>
      %34 = select %30, %31, %33 : tile<128xi1>, tile<128xi32>
      %35 = select %28, %34, %21 : tile<128xi1>, tile<128xi32>
      %36 = select %28, %24, %27 : tile<128xi1>, tile<128xi32>
      %37 = addi %22, %36 : tile<128xi32>
      continue %35, %37, %23 : tile<128xi32>, tile<128xi32>, token
    }
    %38 = reshape %arg1 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %39 = broadcast %38 : tile<1xptr<i32>> -> tile<128xptr<i32>>
    %40 = offset %39, %7 : tile<128xptr<i32>>, tile<128xi32> -> tile<128xptr<i32>>
    %41 = store_ptr_tko weak %40, %18 token=%19 : tile<128xptr<i32>>, tile<128xi32> -> token
    return
  }
}
