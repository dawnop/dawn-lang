cuda_tile.module @m {
  entry @max_subarray(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<i32>>) {
    %0 = make_token : token
    %1 = constant <i32: 0> : tile<i32>
    %2 = constant <i32: 0> : tile<128xi32>
    %3 = reshape %1 : tile<i32> -> tile<1xi32>
    %4 = broadcast %3 : tile<1xi32> -> tile<128xi32>
    %5 = iota : tile<128xi32>
    %6 = addi %4, %5 : tile<128xi32>
    %7 = constant <i32: 100> : tile<128xi32>
    %8 = cmpi less_than %6, %7, signed : tile<128xi32> -> tile<128xi1>
    %9 = reshape %arg0 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %10 = broadcast %9 : tile<1xptr<i32>> -> tile<128xptr<i32>>
    %11 = offset %10, %6 : tile<128xptr<i32>>, tile<128xi32> -> tile<128xptr<i32>>
    %12, %13 = load_ptr_tko weak %11, %8, %2 token=%0 : tile<128xptr<i32>>, tile<128xi1>, tile<128xi32> -> tile<128xi32>, token
    %14 = scan %12 dim=0 reverse=false identities=[0 : i32] : tile<128xi32> -> tile<128xi32> (%15: tile<i32>, %16: tile<i32>) {
      %17 = addi %15, %16 : tile<i32>
      yield %17 : tile<i32>
    }
    %18 = constant <i32: 7> : tile<128xi32>
    %19 = cmpi greater_than_or_equal %6, %18, signed : tile<128xi32> -> tile<128xi1>
    %20 = constant <i32: 107> : tile<128xi32>
    %21 = cmpi less_than %6, %20, signed : tile<128xi32> -> tile<128xi1>
    %22 = constant <i1: 0> : tile<128xi1>
    %23 = select %19, %21, %22 : tile<128xi1>, tile<128xi1>
    %24 = constant <i32: 7> : tile<128xi32>
    %25 = subi %6, %24 : tile<128xi32>
    %26 = maxi %25, %2 signed : tile<128xi32>
    %27 = reshape %arg0 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %28 = broadcast %27 : tile<1xptr<i32>> -> tile<128xptr<i32>>
    %29 = offset %28, %26 : tile<128xptr<i32>>, tile<128xi32> -> tile<128xptr<i32>>
    %30, %31 = load_ptr_tko weak %29, %23, %2 token=%13 : tile<128xptr<i32>>, tile<128xi1>, tile<128xi32> -> tile<128xi32>, token
    %32 = scan %30 dim=0 reverse=false identities=[0 : i32] : tile<128xi32> -> tile<128xi32> (%33: tile<i32>, %34: tile<i32>) {
      %35 = addi %33, %34 : tile<i32>
      yield %35 : tile<i32>
    }
    %36 = constant <i32: 6> : tile<128xi32>
    %37 = cmpi greater_than_or_equal %6, %36, signed : tile<128xi32> -> tile<128xi1>
    %38 = constant <i32: 100> : tile<128xi32>
    %39 = cmpi less_than %6, %38, signed : tile<128xi32> -> tile<128xi1>
    %40 = constant <i1: 0> : tile<128xi1>
    %41 = select %37, %39, %40 : tile<128xi1>, tile<128xi1>
    %42 = subi %14, %32 : tile<128xi32>
    %43 = constant <i32: -2000000000> : tile<128xi32>
    %44 = select %41, %42, %43 : tile<128xi1>, tile<128xi32>
    %45 = constant <i32: 1> : tile<i32>
    %46 = muli %1, %45 : tile<i32>
    %47 = reduce %44 dim=0 identities=[-2000000000 : i32] : tile<128xi32> -> tile<i32> (%48: tile<i32>, %49: tile<i32>) {
      %50 = maxi %48, %49 signed : tile<i32>
      yield %50 : tile<i32>
    }
    %51 = reshape %47 : tile<i32> -> tile<1xi32>
    %52 = broadcast %51 : tile<1xi32> -> tile<1xi32>
    %53 = reshape %46 : tile<i32> -> tile<1xi32>
    %54 = broadcast %53 : tile<1xi32> -> tile<1xi32>
    %55 = iota : tile<1xi32>
    %56 = addi %54, %55 : tile<1xi32>
    %57 = reshape %arg1 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %58 = broadcast %57 : tile<1xptr<i32>> -> tile<1xptr<i32>>
    %59 = offset %58, %56 : tile<1xptr<i32>>, tile<1xi32> -> tile<1xptr<i32>>
    %60 = store_ptr_tko weak %59, %52 token=%31 : tile<1xptr<i32>>, tile<1xi32> -> token
    return
  }
}
