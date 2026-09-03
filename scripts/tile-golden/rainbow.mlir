cuda_tile.module @m {
  entry @rainbow(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<i32>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = reshape %5 : tile<i32> -> tile<1xi32>
    %7 = broadcast %6 : tile<1xi32> -> tile<128xi32>
    %8 = iota : tile<128xi32>
    %9 = addi %7, %8 : tile<128xi32>
    %10 = constant <i32: 1000> : tile<128xi32>
    %11 = cmpi less_than %9, %10, signed : tile<128xi32> -> tile<128xi1>
    %12 = constant <i32: 0> : tile<128xi32>
    %13 = reshape %arg0 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %14 = broadcast %13 : tile<1xptr<i32>> -> tile<128xptr<i32>>
    %15 = offset %14, %9 : tile<128xptr<i32>>, tile<128xi32> -> tile<128xptr<i32>>
    %16, %17 = load_ptr_tko weak %15, %11, %12 token=%0 : tile<128xptr<i32>>, tile<128xi1>, tile<128xi32> -> tile<128xi32>, token
    %18 = constant <i32: -1640531535> : tile<128xi32>
    %19 = muli %16, %18 : tile<128xi32>
    %20 = constant <i32: 15> : tile<128xi32>
    %21 = shri %19, %20 unsigned : tile<128xi32>
    %22 = xori %19, %21 : tile<128xi32>
    %23 = constant <i32: 2135587861> : tile<128xi32>
    %24 = addi %22, %23 : tile<128xi32>
    %25 = constant <i32: 13> : tile<128xi32>
    %26 = shri %24, %25 signed : tile<128xi32>
    %27 = xori %24, %26 : tile<128xi32>
    %28 = constant <i32: -2048144777> : tile<128xi32>
    %29 = muli %27, %28 : tile<128xi32>
    %30 = constant <i32: 16> : tile<128xi32>
    %31 = shri %29, %30 unsigned : tile<128xi32>
    %32 = xori %29, %31 : tile<128xi32>
    %33 = constant <i32: -1640531535> : tile<128xi32>
    %34 = muli %32, %33 : tile<128xi32>
    %35 = constant <i32: 15> : tile<128xi32>
    %36 = shri %34, %35 unsigned : tile<128xi32>
    %37 = xori %34, %36 : tile<128xi32>
    %38 = constant <i32: 2135587861> : tile<128xi32>
    %39 = addi %37, %38 : tile<128xi32>
    %40 = constant <i32: 13> : tile<128xi32>
    %41 = shri %39, %40 signed : tile<128xi32>
    %42 = xori %39, %41 : tile<128xi32>
    %43 = constant <i32: -2048144777> : tile<128xi32>
    %44 = muli %42, %43 : tile<128xi32>
    %45 = constant <i32: 16> : tile<128xi32>
    %46 = shri %44, %45 unsigned : tile<128xi32>
    %47 = xori %44, %46 : tile<128xi32>
    %48 = constant <i32: -1640531535> : tile<128xi32>
    %49 = muli %47, %48 : tile<128xi32>
    %50 = constant <i32: 15> : tile<128xi32>
    %51 = shri %49, %50 unsigned : tile<128xi32>
    %52 = xori %49, %51 : tile<128xi32>
    %53 = constant <i32: 2135587861> : tile<128xi32>
    %54 = addi %52, %53 : tile<128xi32>
    %55 = constant <i32: 13> : tile<128xi32>
    %56 = shri %54, %55 signed : tile<128xi32>
    %57 = xori %54, %56 : tile<128xi32>
    %58 = constant <i32: -2048144777> : tile<128xi32>
    %59 = muli %57, %58 : tile<128xi32>
    %60 = constant <i32: 16> : tile<128xi32>
    %61 = shri %59, %60 unsigned : tile<128xi32>
    %62 = xori %59, %61 : tile<128xi32>
    %63 = reshape %arg1 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %64 = broadcast %63 : tile<1xptr<i32>> -> tile<128xptr<i32>>
    %65 = offset %64, %9 : tile<128xptr<i32>>, tile<128xi32> -> tile<128xptr<i32>>
    %66 = store_ptr_tko weak %65, %62, %11 token=%17 : tile<128xptr<i32>>, tile<128xi32>, tile<128xi1> -> token
    return
  }
}
